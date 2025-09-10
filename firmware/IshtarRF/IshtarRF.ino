// IshtarRF Firmware
// Copyright (c) 2025 Cyber ducky
// SPDX-License-Identifier: AGPL-3.0-only


#include <Arduino.h>
#include <SPI.h>
#include <ELECHOUSE_CC1101_SRC_DRV.h>

//Pins
#define PIN_SCK   14
#define PIN_MISO  12
#define PIN_MOSI  13
#define PIN_CS    5
#define PIN_GDO0  2
#define PIN_GDO2  4

#ifndef CC1101_IOCFG0
  #define CC1101_IOCFG0 0x02
#endif
#ifndef CC1101_SIDLE
  #define CC1101_SIDLE  0x36
#endif
#ifndef CC1101_SFRX
  #define CC1101_SFRX   0x3A
#endif
#ifndef CC1101_SFTX
  #define CC1101_SFTX   0x3B
#endif

//Serial
#define SERIAL_BAUD 115200

//RAW capture
#define RAW_MAX_PULSES        10000
#define RAW_IDLE_TIMEOUT_US   8000

//Defaults
static double g_freq = 315.000;   // MHz
static String g_mod  = "OOK";
static double g_br   = 3.30;      // kbps
static double g_dev  = 30.0;      // kHz
static int    g_txp  = 0;         // dBm

//RAW state
volatile bool     raw_active        = false;
volatile uint32_t raw_last_edge_us  = 0;
volatile int      raw_count         = 0;
volatile uint32_t raw_pulses[RAW_MAX_PULSES];
static   uint32_t raw_timeout_us    = RAW_IDLE_TIMEOUT_US;
static   uint32_t raw_frame_start_us = 0;

enum RxMode { RX_NONE, RX_PACKET, RX_RAW };
static RxMode rxMode = RX_NONE;

//Utils
static void jsonLine(const String& s){ Serial.println(s); }
static String jsonEscape(const String& in){
  String out; out.reserve(in.length()+8);
  for(char c: in){ if(c=='"'||c=='\\'){out+='\\'; out+=c;} else if(c=='\n') out+="\\n"; else out+=c; }
  return out;
}
static void sendOK(const char* of){ String s="{\"event\":\"ok\",\"of\":\""; s+=of; s+="\"}"; jsonLine(s); }
static void sendERR(const String& msg){ String s="{\"event\":\"error\",\"msg\":\""; s+=jsonEscape(msg); s+="\"}"; jsonLine(s); }

//RAW ISR
void IRAM_ATTR gdo0_isr(){
  if(!raw_active) return;
  uint32_t now = micros();
  uint32_t dt  = now - raw_last_edge_us;
  raw_last_edge_us = now;
  if(raw_count < RAW_MAX_PULSES){
    raw_pulses[raw_count++] = dt;
  }
}
static void rawStart(){
  raw_count = 0;
  raw_active = true;
  raw_last_edge_us = micros();
  raw_frame_start_us = raw_last_edge_us;
  attachInterrupt(digitalPinToInterrupt(PIN_GDO0), gdo0_isr, CHANGE);
}
static void rawStop(){
  raw_active = false;
  detachInterrupt(digitalPinToInterrupt(PIN_GDO0));
}

//CC1101 helpers
static bool applyRadioConfig(){
  ELECHOUSE_cc1101.setSpiPin(PIN_SCK, PIN_MISO, PIN_MOSI, PIN_CS);
  ELECHOUSE_cc1101.Init();                 // void
  ELECHOUSE_cc1101.setGDO(PIN_GDO0, PIN_GDO2);
  if (!ELECHOUSE_cc1101.getCC1101()) return false;

  ELECHOUSE_cc1101.setMHZ(g_freq);
  if(g_mod == "OOK"){
    ELECHOUSE_cc1101.setModulation(2);     // ASK/OOK
  }else{
    ELECHOUSE_cc1101.setModulation(0);     // 2-FSK
    ELECHOUSE_cc1101.setDeviation(g_dev);
  }
  ELECHOUSE_cc1101.setDRate(g_br);
  ELECHOUSE_cc1101.setRxBW(270.0);
  ELECHOUSE_cc1101.setPA(g_txp);
  return true;
}

static void enterAsyncRx(){
  ELECHOUSE_cc1101.setPktFormat(3);
  uint8_t v = ELECHOUSE_cc1101.SpiReadReg(CC1101_IOCFG0);
  v &= 0xC0; v |= 0x0D;
  ELECHOUSE_cc1101.SpiWriteReg(CC1101_IOCFG0, v);
  ELECHOUSE_cc1101.SpiStrobe(CC1101_SFRX);
  ELECHOUSE_cc1101.SetRx();
  pinMode(PIN_GDO0, INPUT);
}

static void enterPacketRx(){
  ELECHOUSE_cc1101.setPktFormat(0);
  ELECHOUSE_cc1101.SpiStrobe(CC1101_SFRX);
  ELECHOUSE_cc1101.SetRx();
  pinMode(PIN_GDO0, INPUT);
}

static void radioForceIdle(){
  ELECHOUSE_cc1101.SpiStrobe(CC1101_SIDLE);
  ELECHOUSE_cc1101.SpiStrobe(CC1101_SFTX);
  ELECHOUSE_cc1101.SpiStrobe(CC1101_SFRX);
  pinMode(PIN_GDO0, INPUT);
}

//Packet RX/TX
static bool rxPacketOnce(String &hex, int &rssi_dbm){
  if (ELECHOUSE_cc1101.CheckReceiveFlag()){
    uint8_t buf[64];
    byte n = ELECHOUSE_cc1101.ReceiveData(buf);
    if(n>0){
      static const char* H="0123456789ABCDEF";
      String h; h.reserve(n*2);
      for(byte i=0;i<n;i++){ h+=H[buf[i]>>4]; h+=H[buf[i]&0x0F]; }
      hex = h;
      rssi_dbm = ELECHOUSE_cc1101.getRssi();
      return true;
    }
  }
  return false;
}
static bool txBytes(const String& hex){
  if(hex.length()%2!=0) return false;
  int n=hex.length()/2; if(n<=0 || n>61) return false; // FIFO ~61B
  uint8_t buf[61];
  auto val=[&](char c)->int{ if(c>='0'&&c<='9')return c-'0'; c=toupper(c); if(c>='A'&&c<='F')return 10+(c-'A'); return -1; };
  for(int i=0;i<n;i++){ int v1=val(hex[2*i]), v2=val(hex[2*i+1]); if(v1<0||v2<0) return false; buf[i]=(v1<<4)|v2; }
  ELECHOUSE_cc1101.SendData(buf, (byte)n);
  return true;
}

//OOK RAW TX
static bool txRawDirect(const uint32_t* pulses, int count, int repeat, int gap_ms, bool invert){
  ELECHOUSE_cc1101.setPktFormat(3);
  uint8_t v = ELECHOUSE_cc1101.SpiReadReg(CC1101_IOCFG0);
  v &= 0xC0; v |= 0x2E;                       // 0x2E = 3-state
  ELECHOUSE_cc1101.SpiWriteReg(CC1101_IOCFG0, v);

  ELECHOUSE_cc1101.SpiStrobe(CC1101_SFTX);
  ELECHOUSE_cc1101.SetTx();

  pinMode(PIN_GDO0, OUTPUT);
  bool level = invert ? HIGH : LOW;
  digitalWrite(PIN_GDO0, level);
  delayMicroseconds(400);

  bool ok = true;
  for(int r=0;r<repeat && ok;r++){
    for(int i=0;i<count;i++){
      level = !level;
      digitalWrite(PIN_GDO0, level);
      uint32_t us = pulses[i]; if(us < 2) us = 2;
      while(us > 16000){ delayMicroseconds(16000); us -= 16000; yield(); }
      delayMicroseconds(us);
    }
    digitalWrite(PIN_GDO0, invert ? HIGH : LOW);

    if(r+1<repeat && gap_ms>0){
      for(int g=0; g<gap_ms; g++){ delay(1); yield(); }
    }
  }

  ELECHOUSE_cc1101.SpiStrobe(CC1101_SIDLE);
  ELECHOUSE_cc1101.SpiStrobe(CC1101_SFTX);
  pinMode(PIN_GDO0, INPUT);
  return ok;
}

//RSSI
static void sendRSSI(){
  int rssi = ELECHOUSE_cc1101.getRssi();
  String s = "{\"event\":\"rssi\",\"value_dbm\":"; s+=String(rssi); s+="}";
  jsonLine(s);
}

//JSON helpers
static bool readJsonLine(String& out){
  static String line;
  while(Serial.available()){
    char c=Serial.read();
    if(c=='\n'){ out=line; line=""; return true; }
    else if(c!='\r'){ line+=c; }
  }
  return false;
}
static double valD(const String& line, const char* k, double def){
  int i=line.indexOf(String("\"")+k+"\""); if(i<0) return def;
  i=line.indexOf(":",i); if(i<0) return def;
  int j=line.indexOf(",",i); if(j<0) j=line.indexOf("}",i); if(j<0) return def;
  String sub=line.substring(i+1,j); sub.replace(":",""); sub.trim(); return sub.toDouble();
}
static int valI(const String& line, const char* k, int def){ return (int)valD(line,k,def); }
static String valS(const String& line, const char* k, const char* def){
  int i=line.indexOf(String("\"")+k+"\""); if(i<0) return String(def);
  i=line.indexOf(":",i); if(i<0) return String(def);
  int q1=line.indexOf("\"",i+1), q2=line.indexOf("\"",q1+1); if(q1<0||q2<0) return String(def);
  return line.substring(q1+1,q2);
}

//Setup / Loop
void setup(){
  Serial.begin(SERIAL_BAUD);
  delay(200);

  if(!applyRadioConfig()){
    sendERR("Radio init failed");
  }

  pinMode(PIN_GDO0, INPUT);
  pinMode(PIN_GDO2, INPUT);

  jsonLine("{\"event\":\"pong\"}");
}

void loop(){
  // Packet RX
  if(rxMode == RX_PACKET){
    String hex; int rssi;
    if(rxPacketOnce(hex, rssi)){
      String s = "{\"event\":\"rx_bytes\",\"hex\":\"";
      s += hex; s += "\",\"rssi_dbm\":"; s += String(rssi); s += "}";
      jsonLine(s);
    }
  }

  // RAW RX continuous
  if(rxMode == RX_RAW && raw_active){
    uint32_t now = micros();
    if(raw_count >= RAW_MAX_PULSES-2 || (now - raw_last_edge_us) > raw_timeout_us){
      rawStop();

      int cnt = raw_count;
      if(cnt >= 4){
        int rssi = ELECHOUSE_cc1101.getRssi();
        uint32_t dur_ms = (now - raw_frame_start_us)/1000UL;

        String s = "{\"event\":\"rx_raw\",\"pulses_us\":[";
        for(int i=0;i<cnt;i++){ s += String((int)raw_pulses[i]); if(i+1<cnt) s += ","; }
        s += "],\"rssi_dbm\":"; s += String(rssi);
        s += ",\"dur_ms\":";    s += String((int)dur_ms);
        s += "}";
        jsonLine(s);
      }
      rawStart();
    }
  }

  // Commands
  String line;
  if(readJsonLine(line)){
    String cmd = valS(line, "cmd", "");
    if(cmd=="ping"){
      jsonLine("{\"event\":\"pong\"}");
    }
    else if(cmd=="recover"){
      radioForceIdle();
      if(applyRadioConfig()) {
        if(rxMode == RX_RAW){ enterAsyncRx(); rawStart(); }
        else if(rxMode == RX_PACKET){ enterPacketRx(); }
        sendOK("recover");
      } else {
        sendERR("recover failed");
      }
    }
    else if(cmd=="set_config"){
      g_freq = valD(line,"freq",g_freq);
      g_mod  = valS(line,"mod", g_mod.c_str());
      g_br   = valD(line,"br_kbps",g_br);
      g_dev  = valD(line,"dev_khz",g_dev);
      g_txp  = valI(line,"tx_power",g_txp);
      if(applyRadioConfig()) sendOK("set_config"); else sendERR("set_config failed");
    }
    else if(cmd=="rx_start"){
      String mode = valS(line,"mode","packet");
      if(mode=="packet"){
        rxMode = RX_PACKET;
        enterPacketRx();
        sendOK("rx_start");
      }else if(mode=="raw_ook"){
        raw_timeout_us = (uint32_t)valI(line,"timeout_ms",8000)*1000UL;
        rxMode = RX_RAW;
        enterAsyncRx();
        rawStart();
        sendOK("rx_start");
      }else{
        sendERR("Unknown rx mode");
      }
    }
    else if(cmd=="rx_stop"){
      if(rxMode==RX_RAW){ rawStop(); }
      radioForceIdle();
      rxMode = RX_NONE;
      sendOK("rx_stop");
    }
    else if(cmd=="get_rssi"){
      sendRSSI();
    }
    else if(cmd=="tx_bytes"){
      String hex = valS(line,"hex","");
      if(txBytes(hex)) sendOK("tx_bytes"); else sendERR("tx_bytes failed");
    }
    else if(cmd=="tx_raw"){
      int b = line.indexOf('['), e = line.indexOf(']', b+1);
      if(b<0 || e<0){ sendERR("tx_raw bad pulses"); }
      else{
        String arr = line.substring(b+1, e);
        int cnt=0, start=0;
        while(start < arr.length() && cnt < RAW_MAX_PULSES){
          int c = arr.indexOf(',', start); if(c<0) c = arr.length();
          String num = arr.substring(start, c); num.trim();
          if(num.length()>0) raw_pulses[cnt++] = (uint32_t)num.toInt();
          start = c+1;
        }
        int rep   = valI(line,"repeat",1);
        int gap   = valI(line,"gap_ms",20);
        String invS = valS(line,"invert","false");
        bool invert = (invS=="true" || invS=="1");

        if(rxMode == RX_RAW) rawStop();
        bool ok = (cnt>0) && txRawDirect((const uint32_t*)raw_pulses, cnt, rep, gap, invert);

        if(rxMode == RX_RAW){ enterAsyncRx(); rawStart(); }
        else if(rxMode == RX_PACKET){ enterPacketRx(); }
        else { radioForceIdle(); }

        if(ok) sendOK("tx_raw"); else sendERR("tx_raw failed");
      }
    }
    else{
      sendERR("Unknown cmd");
    }
  }
}

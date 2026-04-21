#include <SPIMemory.h>
#include <SD.h>
#include <SPI.h>

// New Omni V1 Beta features: Now supports bidirectional trigger mode to let PC becomes master device. Can we used to pair with python script to hook with Cygnus
// Omni V2.1 Beta features: Now fully works in match with the python file on PC side.
// Omni V2.1.1 Beta features: Added the feature of customize filename to prevent unwanted overwrite. Also default pinstate is set to LOW to prevent mismatch.
// Omni V2.1.1 Beta needs to pair with arduino_logger_v2.1.1.py

#define TRIG_PIN 2   // 輸入或輸出：MRI Trigger
#define LED_IND  8   // 輸出：本地指示LED（確認trigger）
#define OUT_PIN  9   // 輸出：光刺激控制 (5V TTL)
#define SD_PIN 4 // 讀寫SD卡的port
#define FLASH_PIN 5 //W25Q64 CS

// 現在的code一次cycle平均大概是6.8微秒,在有外部刺激的情況下至多達到15~16微秒,外部trigger只要大於50微秒都可以。

// --- 定義狀態使得Arduino以有限狀態機的方式運作
enum State {
  IDLE, // 等待Trigger
  REST0, //初始休息60秒
  REST, //休息30秒
  BLINK_ON, //亮1ms休息999ms
  BLINK_OFF, //亮之後休息的時間
  FINISHED //完成的狀態
};

// --- 溝通模式(決定PC是slave還是master) ---
bool mode;

// --- 狀態紀錄器 ---
State currentState = IDLE; // 設定初始狀態
int blink_count = 0; // 紀錄單次cycle裡刺激幾次了
int cycle_count = 0; // 紀錄現在Cycle到第幾個loop
unsigned long previousMillis = 0UL;
volatile bool trig_flag = false;

// --- 設定sequence樣態 ---
// sequence時間總長計算方式: init_rest_time + seq元素總數*(event_dur*event_count_per_cycle + rest_time)，單位為毫秒
unsigned long init_rest_time = 10000UL; // 初始rest的目的是為了抵銷掉MRI的dummy scan trigger和實際掃描之間的時間誤差、等待初始不可用的100秒跑完，並且再收集沒刺激過的reference數據，一共約45 + 100 + 30 ~ 175秒
unsigned long rest_time = 10000UL; // 每個cycle的rest time長度
unsigned long seq[] = {1UL, 10UL, 1UL, 10UL}; // 總共有幾個cycle，依順序每個cycle的光刺激時長(LED燈開啟的時間)是多久
unsigned long event_dur = 100UL; // 每次刺激的event的總長度為多少(兩次LED開啟的時間間隔)
int event_count_per_cycle = 100; // 每個cycle有幾個event(LED燈亮幾次)

// --- 宣告FLASH物件 ---
SPIFlash flash(FLASH_PIN);
bool saved_to_sd = 0;
char FILE_NAME[13];
char FILE_PREFIX[7];
int FILE_ORDER = 0;

// --- 緩衝區設定 ---
// W25Q64 的single page是256 bytes,所以我們整理成252 bytes一個bundle來填充256 byte一個空間
const int EVENT_SIZE = 6;
const int EVENTS_PER_PAGE = 42;
const int BUFFER_SIZE = 252;
const int PAGE_SIZE = 256;

byte pageBuffer[BUFFER_SIZE];
int bufferIndex = 0;
uint32_t currentFlashAddr = 36864; // 追蹤flash當前寫到的位置
uint32_t readAddr = currentFlashAddr;

// --- 寫入Flash的核心函式
void saveToFlashBuffer(unsigned long timestamp, byte type, byte state, bool forceWrite) {
  // 1. 將數據填入 Arduino 的 RAM Buffer
  pageBuffer[bufferIndex++] = (timestamp >> 24) & 0xFF;
  pageBuffer[bufferIndex++] = (timestamp >> 16) & 0xFF;
  pageBuffer[bufferIndex++] = (timestamp >> 8) & 0xFF;
  pageBuffer[bufferIndex++] = timestamp & 0xFF;
  pageBuffer[bufferIndex++] = type; // 0:Trigger, 1:LED Output, 2:Elecctric stimulation
  pageBuffer[bufferIndex++] = state; // in milliseconds

  // 2. 檢查 Buffer 是否已經滿了，是的話寫入 W25Q64
  if (bufferIndex >= BUFFER_SIZE || forceWrite) {
    if (flash.writeByteArray(currentFlashAddr, pageBuffer, BUFFER_SIZE)) {
      currentFlashAddr += PAGE_SIZE;
      bufferIndex = 0; // clear the buffer
    }
    else {
      Serial.println(F("Flash Write Error!"));
    }
  }
}

// --- 從 Flash 轉存到 SD ---
void dumpFlashToSD() {
  if (currentFlashAddr == readAddr && bufferIndex == 0) return; // 沒資料

  Serial.println(F("Dumping Flash to SD..."));
  File dataFile = SD.open(FILE_NAME, FILE_WRITE);
  
  if (dataFile) {
    
    // 1. 先讀取已經寫入 Flash 的整頁資料
    while (readAddr < currentFlashAddr) {
      flash.readByteArray(readAddr, pageBuffer, BUFFER_SIZE);
      
      for(int i=0; i<BUFFER_SIZE; i+=EVENT_SIZE) {
        unsigned long ts = (unsigned long)pageBuffer[i] << 24 | (unsigned long)pageBuffer[i+1] << 16 | (unsigned long)pageBuffer[i+2] << 8 | pageBuffer[i+3];
        byte type = pageBuffer[i+4];
        byte state = pageBuffer[i+5];
      
        dataFile.print(ts); dataFile.print(",");
        dataFile.print(type); dataFile.print(",");
        dataFile.println(state);
    }
      
      readAddr += PAGE_SIZE;
    }

    dataFile.close();
    Serial.println(F("Dump Done."));
    
    // 重置buffer，步進一次儲存到SD Card的檔案名稱
    bufferIndex = 0;
    FILE_ORDER += 1;
    sprintf(FILE_NAME, "%s_%d.txt", FILE_PREFIX, FILE_ORDER);
    
    // 擦除 Flash 準備下一次使用 (Block Erase 比較快)
    // 這裡我們選擇只把指標歸零，實務上建議在此時執行 eraseChip 或 eraseSector
    // 但 erase 很久，建議在 setup 做，或者確保 flash 容量夠大不需一直擦除
  } else {
    Serial.println(F("SD Error!"));
  }
}

void onFalling() {
  if (currentState == IDLE) {
    trig_flag = true;   // 第一次偵測才觸發
  }
}

void setup() {
  Serial.begin(115200);

  delay(1000UL); // Prevent the message from bursting out and thus missed by PC terminal

  // 1. 初始化 SD
  Serial.print(F("Init SD card..."));
  if (!SD.begin(SD_PIN)) {
    Serial.println(F("Init failed."));
    return;
  }

  // 2. 初始化 Flash
  Serial.println(F("Init Flash..."));
  flash.begin();
  
  // 重要：實驗開始前先確認 Flash 目前使用到哪裡，如果還有很多額外空間就把初始address往後挪，已經快滿就清空 (Erase Chip)，這個功能是為了減緩Flash wear
  // 如果動用到EraseChip，這會花幾秒鐘，LED 會停住，這是正常的
  Serial.println(F("Erasing Flash (Please Wait)..."));
  for (uint32_t addr = currentFlashAddr; addr <= 0x800000; addr += 0x100) {
    flash.readByteArray(addr, pageBuffer, BUFFER_SIZE); // 將 flash pages 讀取到記憶體內，我們直接借用已經宣告好的 pageBuffer

    bool clean = false;
    for (int i = 0; i < BUFFER_SIZE; i++) {
      if (pageBuffer[i] != 0xFF) {break;} // 只要偵測到一個不是0xFF就立刻跳過這個page的檢測,因為代表一定有東西 
      if (i == BUFFER_SIZE-1) {clean = true;} // 如果loop成功跑到最後就代表這個page是乾淨的,這個page往後都沒有寫過(因為都是順序讀寫)
    }

    if (clean == true) { // 如果page為clean就代表找到乾淨的開頭了, 更新address開頭並結束初始化
      currentFlashAddr = addr;
      readAddr = addr;
      break;
    }

    if (addr >= 0x700000) { // 如果已經掃描到最後 8分之1, 代表空間剩不到1MB, 就直接抹除整個chip
      flash.eraseChip();
    }
  }
  Serial.println(F("Flash Ready. Starting at address:"));
  Serial.println(readAddr);
  
  delay(2000); // This part will let PC have time to communicate and shake hands with Arduino, because Python script will treat responding next question as shake hands.

  // Request user to input data file name
  Serial.println(F("Please enter file name prefix:(Max 6 Char)"));
  while (Serial.available() == 0) {}

  int index = 0;
  while(index < 7) {
    if (Serial.available() > 0) {
      char c = Serial.read();
      // 如果讀到換行符號就停止
      if (c == '\n' || c == '\r' || index >= 6) break;
      FILE_PREFIX[index++] = c;
    }
  }
  FILE_PREFIX[index] = '\0';
  strcpy(FILE_NAME, FILE_PREFIX);
  strcat(FILE_NAME, "_0.txt\0");


  Serial.println(FILE_NAME);

  delay(500);

  // Request user to input com mode.
  Serial.println(F("Please enter com mode: (0 = PC is master/1 = PC is slave)"));
  while (Serial.available() == 0) {}
  char input = Serial.read();

  // Define variable according to com mode set.
  if (input == '0') {
    mode = 0;
    Serial.println(F("Mode set to: 0"));
  }
  else if (input == '1') {
    mode = 1;
    Serial.println(F("Mode set to: 1"));
  }
  else {
    mode = 1; // 預設值
    Serial.println(F("Invalid input, defaulting to Mode 1"));
  }

  // 輸出端
  pinMode(LED_IND, OUTPUT);
  pinMode(OUT_PIN, OUTPUT);

  digitalWrite(LED_IND, LOW);
  digitalWrite(OUT_PIN, LOW);

  // 輸入端
  if (mode) {
    pinMode(TRIG_PIN, INPUT_PULLUP); // 平時HIGH，trigger落地時FALLING
  
    // 設計一個如果偵測到定義腳位有訊號就打斷系統進入onFalling函數的功能
    attachInterrupt(digitalPinToInterrupt(TRIG_PIN), onFalling, FALLING);
  }
  else {
    pinMode(TRIG_PIN, OUTPUT);
    digitalWrite(TRIG_PIN, HIGH);
  }


  Serial.println(F("Initialization done."));

  Serial.println(F("Sys ready — waiting for TRG."));
}

void loop() {
  //static unsigned long counter = 0UL; //This is for measuring latency when accessing FLASH
  unsigned long currentMillis = millis(); //  獲取開機時間
  static unsigned long lastTrigMillis = currentMillis; // 第一次宣告的時候, 要讓lastTrig從現在時間開始

  // The below block is to check for TRIG_PIN state (different for different mode, so an if statement)
  int trigPinState = digitalRead(TRIG_PIN); // 讀取這次的數據, 與mode為何無關
  if (mode){
    static int lastInputState = LOW; // 定義一個函數紀錄上次輸入的狀態
    if (trigPinState == LOW && lastInputState == HIGH) {
      saveToFlashBuffer(currentMillis, 0, 0, false); // 狀態切換時計算外部trigger
    }
    lastInputState = trigPinState;
  }
  else if (!mode){ 
    if (currentMillis - lastTrigMillis >= 1UL && trigPinState == LOW) { // 當達到1毫秒且trig_pin還沒被調回去時調整trig_pin, 所以輸出的TRIG_OUT總共1毫秒長
      digitalWrite(TRIG_PIN, HIGH);
    }
    else if (currentMillis - lastTrigMillis >= 50UL && currentState != IDLE && currentState != FINISHED) { // 50毫秒時重新開始計時, 假設接收端需要的TRIG interval是50ms, 20Hz
      // 這個條件是要等到state不是IDLE以後才能開始, 這樣Trig_pin才不會錯誤輸出
      digitalWrite(TRIG_PIN, LOW);
      lastTrigMillis = currentMillis;
      saveToFlashBuffer(currentMillis, 0 , 1, false); // Trigger啟動, 記錄起來
    }
  }

  switch (currentState) {
    case IDLE:
      if (trig_flag) {
        Serial.println(F("TRGed. Starting..."));
        //counter = 0;
        trig_flag = false;
        cycle_count = 0;

        if (!mode) { // 當mode = 0時, 要輸出trigger, 同時記錄
          digitalWrite(TRIG_PIN, LOW);
          lastTrigMillis = currentMillis;
          saveToFlashBuffer(currentMillis, 0, 1, false);
        }

        currentState = REST0;
        previousMillis = currentMillis;
      }

      break;

    // 以下為初始rest，目的是為了抵銷掉MRI的dummy scan trigger和實際掃描之間的時間誤差、等待初始不可用的100秒跑完，並且再收集沒刺激過的reference數據，一共約45 + 100 + 30 ~ 175秒
    case REST0:
      if (currentMillis - previousMillis >= init_rest_time) {
        blink_count = 0;

        //  開LED燈
        digitalWrite(LED_IND, HIGH);
        digitalWrite(OUT_PIN, HIGH);
        currentState = BLINK_ON;
        previousMillis = currentMillis;
      }

      break;

    case REST:
      if (currentMillis - previousMillis >= rest_time) {
        cycle_count++; // rest結束代表一個cycle跑完了，cycle計數器+1
        blink_count = 0;
        
        //  開LED燈
        digitalWrite(LED_IND, HIGH);
        digitalWrite(OUT_PIN, HIGH);

        if (cycle_count < sizeof(seq)/sizeof(seq[0])) { // 確定cycle總數少於seq的數量
          currentState = BLINK_ON;
          }
        else {
          currentState = FINISHED; // 系統發現預定seq已經做完, 刺激結束
        }
        previousMillis = currentMillis;
      }

      break;

    // 以下為BLINK_ON狀態的設定值，判斷LED開啟的時間是否已經達到seq array裡面設定的數值
    case BLINK_ON:
      if (currentMillis - previousMillis >= seq[cycle_count]) {
        digitalWrite(LED_IND, LOW);
        digitalWrite(OUT_PIN, LOW);
        currentState = BLINK_OFF;
        saveToFlashBuffer(previousMillis, 1, lowByte(seq[cycle_count]), false); //讓系統紀錄previousMillis才不會低估後面的休息時間, lowByte提取unsigned long裡面末尾一個byte的資訊
        previousMillis = currentMillis;
      }

      break;

    case BLINK_OFF:
      if (currentMillis - previousMillis >= event_dur - seq[cycle_count]) {
        blink_count++;

        if (blink_count < event_count_per_cycle) {
          //  開LED燈
          digitalWrite(LED_IND, HIGH);
          digitalWrite(OUT_PIN, HIGH);
          currentState = BLINK_ON;
        }
        else {
          currentState = REST;
        }
        previousMillis = currentMillis;
      }

      break;

    case FINISHED:
      if (saved_to_sd == 0) {
        //Serial.println(counter);
        saveToFlashBuffer(currentMillis, 3, 1, true);
        Serial.println(F("Trigger Finished. Saving Data to SD card..."));
        dumpFlashToSD();
        saved_to_sd = 1;
        previousMillis = currentMillis;
      }

      break;
  }

  // 可用序列埠輸入 'r' 來重置
  if (Serial.available()) {
    char c = Serial.read();
    if (c == 'r' || c == 'R') {
      // 強制回歸初始狀態
      currentState = IDLE;
      trig_flag = false;
      saved_to_sd = 0;
      digitalWrite(LED_IND, LOW);
      digitalWrite(OUT_PIN, LOW);
      Serial.println(F("Reset CMD received — kill all process and reset to wait for trigger."));
    }
    else if (c == 's' && currentState == IDLE) {
      // 確定是IDLE state後, 就啟動trig flag, 下一次loop進入IDLE state就會啟動偵測
        trig_flag = true;
        previousMillis = currentMillis;
    }
  }
  //counter++;
}

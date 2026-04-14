import serial
import threading
import time
from datetime import datetime
import csv
from pylsl.pylsl import StreamInlet, resolve_stream

# === 設定區 ===
COM_MODE = 1 # 0 is PC being master/ 1 is PC being slave
ARDUINO_ONLY_MODE = False
PORT = 'COM3'
BAUD_RATE = 115200
ARDUINO_SHAKE_HAND_PROMPT = ["Please enter file name prefix:(Max 6 Char)",
                             "Please enter com mode: (0 = PC is master/1 = PC is slave)",
                             "Sys ready — waiting for TRG.",
                             "Reset CMD received — kill all process and reset to wait for trigger."]
# ============

log_data = []  # 儲存 Log 的列表
eeg_data = [] # 儲存EEG的數據
is_running = True  # 控制執行緒的開關
arduino_ready = False # 讓主程序知道Arduino已經準備就緒
lsl_ready = False # 讓主程序知道EEG已經開始收錄


def get_timestamp():
    """獲取精確到毫秒的系統時間字串"""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]


def listen_to_arduino(ser):
    """背景執行緒 1：專職監聽 Arduino 傳來的資訊"""
    global is_running, arduino_ready, lsl_ready, ARDUINO_SHAKE_HAND_PROMPT, log_data

    while is_running:
        try:
            if ser.in_waiting > 0:
                raw_data = ser.readline()
                recv_time = get_timestamp()

                try:
                    msg = raw_data.decode('utf-8').strip()
                except UnicodeDecodeError:
                    msg = "[解碼錯誤]"

                if msg:
                    log_data.append([recv_time, "RX (Arduino)", msg])
                    print(f"\r[{recv_time}] [Arduino 回傳]: {msg}\n> ", end="", flush=True)

                    # The below is for Python to shake hand with Arduino
                    if msg == ARDUINO_SHAKE_HAND_PROMPT[0]:
                        file_prefix = recv_time[5:13]
                        file_prefix = file_prefix.replace(" ", "")
                        file_prefix = file_prefix.replace(":", "")
                        file_prefix = file_prefix.replace("-", "")
                        ser.write((file_prefix + '\n').encode('utf-8'))
                        log_data.append([recv_time, "SYSTEM", "系統已自動將檔名前綴設為 " + file_prefix])
                        print(f"\r[{recv_time}] 系統已自動將模式設為 系統已自動將檔名前綴設為 " + file_prefix)
                        continue

                    elif msg == ARDUINO_SHAKE_HAND_PROMPT[1]:
                        ser.write((str(COM_MODE) + '\n').encode('utf-8'))
                        log_data.append([recv_time, "SYSTEM", "系統已自動將模式設為 mode " + str(COM_MODE) + " (PC is master)"])
                        print(f"\r[{recv_time}] 系統已自動將模式設為 mode " + str(COM_MODE) + " (PC is master)")
                        continue

                    elif msg == ARDUINO_SHAKE_HAND_PROMPT[2]:
                        arduino_ready = True
                        continue

                    elif msg == ARDUINO_SHAKE_HAND_PROMPT[3]:
                        arduino_ready = True
                        time.sleep(1)
                continue

            # The if statement is for when both conditions are met then starting scan
            if (arduino_ready and lsl_ready) and (not COM_MODE):
                ser.write('s\n'.encode('utf-8'))
                recv_time = get_timestamp()
                log_data.append([recv_time, "SYSTEM", "系統已經自動觸發 Arduino Trigger"])
                print(f"\r[{recv_time}] 系統已經自動觸發 Arduino Trigger)")
                arduino_ready = False

        except serial.SerialException:
            print("\n[錯誤] 失去與 Arduino 的連線。")
            is_running = False
            break

        time.sleep(0.0005)


def listen_to_lsl(inlet):
    """背景執行緒 2：專職監聽 LSL EEG 訊號"""
    global is_running, arduino_ready, lsl_ready, log_data
    lsl_ready = True # 進入這個function就代表lsl成功收到訊號了

    while is_running:
        # 使用 timeout 參數，確保即使沒有資料，迴圈也能繼續運行並檢查 is_running 狀態
        # timeout 設為 0.1 秒，避免卡死
        sample, lsl_timestamp = inlet.pull_sample(timeout=0.1)

        if lsl_timestamp is not None:
            # 接到訊號的瞬間，立刻抓取 Python 系統時間
            sys_time = get_timestamp()

            # 將 LSL 原生的時間戳與生理數據轉為字串
            # 將 LSL timestamp 也記錄下來，因為它對時間對位 (Time Alignment) 非常有幫助
            data_str = f"LSL_TS: {lsl_timestamp:.5f} | Data: {sample}"

            # 存入 Log，但不印在畫面上以免洗版
            eeg_data.append([sys_time, "RX (EEG)", data_str])


def starting_arduino(port, baud_rate):
    print(f"正在嘗試連接 {port} (Baud: {baud_rate})...")
    try:
        ser = serial.Serial(port, baud_rate, timeout=0.01)
        time.sleep(0.2)
    except Exception as e:
        print(f"連線失敗，請確認 Arduino 是否接上且未被佔用。\n錯誤訊息: {e}")
        time.sleep(2)
        return starting_arduino(port, baud_rate)

    # After successfully starting arduino
    sys_start = get_timestamp()
    log_data.append([sys_start, "SYSTEM", f"已成功連接 Arduino ({PORT})"])
    print(f"[{sys_start}] [系統] Arduino 連接成功！")

    # 啟動 Arduino 監聽執行緒
    arduino_thread = threading.Thread(target=listen_to_arduino, args=(ser,), daemon=True)
    arduino_thread.start()

    return ser, arduino_thread


def starting_lsl():
    print("\n[系統] 正在尋找區網內的 EEG stream...")
    # 注意：這裡會卡住直到找到 LSL Stream 為止
    streams = resolve_stream('type', 'EEG')
    inlet = StreamInlet(streams[0])

    sys_start = get_timestamp()
    log_data.append([sys_start, "SYSTEM", "已成功連接 EEG"])
    print(f"[{sys_start}] [系統] 成功連接 EEG Stream！等待 Start Marker...")
    print("> ", end="", flush=True)  # 恢復輸入提示字元

    streams_0 = resolve_stream('type', 'Markers')
    inlet_0 = StreamInlet(streams_0[0])
    while True:
        sample, lsl_timestamp = inlet.pull_sample()
        sys_start = get_timestamp()
        log_data.append([sys_start, "SYSTEM", f"已於 {lsl_timestamp} 接收到 EEG Marker: {sample[0]}"])
        print(f"[{sys_start}] [系統] 已於LSL Time: {lsl_timestamp} 接收到EEG Marker: {sample[0]}，開始背景紀錄資料...")
        print("> ", end="", flush=True)  # 恢復輸入提示字元
        break

    # 啟動 LSL 執行緒
    lsl_thread = threading.Thread(target=listen_to_lsl, args=(inlet,), daemon=True)
    lsl_thread.start()

    return inlet, lsl_thread


def main():
    global is_running, arduino_ready, lsl_ready, log_data

    # --- 1. 初始化 Arduino 連線 ---
    [ser, arduino_thread] = starting_arduino(PORT, BAUD_RATE)

    time.sleep(5) # Let main thread sleep for 5 seconds in case all commands are crammed together

    # --- 2. 啟動 LSL 執行緒 ---
    if not ARDUINO_ONLY_MODE:
        [inlet, lsl_thread] = starting_lsl()
    else:
        lsl_ready = True

    # --- 3. 主執行緒：處理使用者輸入 ---
    print("--------------------------------------------------")
    print("請直接在下方輸入指令並按 Enter 送出。")
    print("輸入 'STOP' (全大寫) 將結束程式並儲存 CSV。")
    print("--------------------------------------------------")

    try:
        while is_running:
            user_input = input("> ")

            if user_input == "STOP":
                log_data.append([get_timestamp(), "SYSTEM", "使用者觸發 STOP 指令，結束紀錄。"])
                is_running = False
                break

            if user_input:
                send_time = get_timestamp()
                ser.write((user_input + '\n').encode('utf-8'))
                log_data.append([send_time, "TX (PC -> Arduino)", user_input])

    except KeyboardInterrupt:
        is_running = False
        log_data.append([get_timestamp(), "SYSTEM", "使用者強制中斷 (Ctrl+C)"])

    # --- 4. 結束與儲存程序 ---
    print("\n[系統] 正在停止紀錄，請稍候...")

    # 留一點時間讓背景執行緒跑完最後一圈並安全結束
    arduino_thread.join(timeout=0.5)
    if not ARDUINO_ONLY_MODE:
        lsl_thread.join(timeout=0.5)
    ser.close()

    # 以當下系統時間建立檔名
    filename = datetime.now().strftime("Sync_Log_%Y%m%d_%H%M%S.csv")
    filename_eeg = datetime.now().strftime("EEG_Log_%Y%m%d_%H%M%S.csv")

    # 寫入 CSV
    with open(filename, mode='w', newline='', encoding='utf-8-sig') as f:
        writer = csv.writer(f)
        writer.writerow(["Timestamp (System)", "Source", "Message / Data"])
        writer.writerows(log_data)

    if eeg_data:
        with open(filename_eeg, mode='w', newline='', encoding='utf-8-sig') as f:
            writer = csv.writer(f)
            writer.writerow(["Timestamp (System)", "Source", "Message / Data"])
            writer.writerows(eeg_data)

    print(f"✅ 所有數據皆已同步儲存至: {filename} 和 {filename_eeg}")


if __name__ == "__main__":
    main()

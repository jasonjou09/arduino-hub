import serial
import threading
import time
from datetime import datetime
import csv
from pylsl import StreamInlet, resolve_streams

# === 設定區 ===
PORT = 'COM3'
BAUD_RATE = 115200
# ============

log_data = []  # 儲存 Log 的列表
is_running = True  # 控制執行緒的開關


def get_timestamp():
    """獲取精確到毫秒的系統時間字串"""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]


def listen_to_arduino(ser):
    """背景執行緒 1：專職監聽 Arduino 傳來的資訊"""
    global is_running
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

        except serial.SerialException:
            print("\n[錯誤] 失去與 Arduino 的連線。")
            is_running = False
            break

        time.sleep(0.001)


def listen_to_lsl():
    """背景執行緒 2：專職監聽 LSL EEG 訊號"""
    global is_running

    print("\n[系統] 正在尋找區網內的 EEG stream...")
    # 注意：這裡會卡住直到找到 LSL Stream 為止
    streams = resolve_stream('type', 'EEG')
    inlet = StreamInlet(streams[0])

    start_time = get_timestamp()
    print(f"[{start_time}] [系統] 成功連接 EEG Stream！開始背景紀錄資料...")
    print("> ", end="", flush=True)  # 恢復輸入提示字元

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
            log_data.append([sys_time, "RX (EEG)", data_str])


def main():
    global is_running

    # --- 1. 初始化 Arduino 連線 ---
    print(f"正在嘗試連接 {PORT} (Baud: {BAUD_RATE})...")
    try:
        ser = serial.Serial(PORT, BAUD_RATE, timeout=0.01)
        time.sleep(2)
        ser.reset_input_buffer()
    except Exception as e:
        print(f"連線失敗，請確認 Arduino 是否接上且未被佔用。\n錯誤訊息: {e}")
        return

    sys_start = get_timestamp()
    log_data.append([sys_start, "SYSTEM", f"已成功連接 Arduino ({PORT})"])
    print(f"[{sys_start}] Arduino 連接成功！")

    # --- 2. 啟動背景執行緒 ---
    # 啟動 LSL 執行緒 (會先尋找 Stream)
    lsl_thread = threading.Thread(target=listen_to_lsl, daemon=True)
    lsl_thread.start()

    # 啟動 Arduino 監聽執行緒
    arduino_thread = threading.Thread(target=listen_to_arduino, args=(ser,), daemon=True)
    arduino_thread.start()

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
    lsl_thread.join(timeout=0.5)
    ser.close()

    # 以當下系統時間建立檔名
    filename = datetime.now().strftime("Sync_Log_%Y%m%d_%H%M%S.csv")

    # 寫入 CSV
    with open(filename, mode='w', newline='', encoding='utf-8-sig') as f:
        writer = csv.writer(f)
        writer.writerow(["Timestamp (System)", "Source", "Message / Data"])
        writer.writerows(log_data)

    print(f"✅ 完美收工！所有數據皆已同步儲存至: {filename}")


if __name__ == "__main__":
    main()
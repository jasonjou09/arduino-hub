import serial # This is package "pyserial"
import threading
import time
from datetime import datetime
import csv
import sys

# === 設定區 ===
PORT = 'COM3'
BAUD_RATE = 115200
# ============

log_data = []  # 儲存 Log 的列表
is_running = True  # 控制執行緒的開關


def get_timestamp():
    """獲取精確到毫秒的系統時間字串"""
    # %f 會輸出微秒 (6位數)，我們切片 [:-3] 保留前3位即為毫秒
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]


def listen_to_arduino(ser):
    """背景執行緒：專職監聽 Arduino 傳來的資訊"""
    global is_running
    while is_running:
        try:
            # 使用 in_waiting 可以不阻塞地檢查緩衝區
            if ser.in_waiting > 0:
                raw_data = ser.readline()
                recv_time = get_timestamp()  # 讀取到的瞬間立刻抓取時間

                try:
                    # 嘗試解碼並移除換行符號
                    msg = raw_data.decode('utf-8').strip()
                except UnicodeDecodeError:
                    msg = "[解碼錯誤 - 非預期字元]"

                if msg:
                    log_data.append([recv_time, "RX (Arduino -> PC)", msg])
                    # 為了不嚴重干擾你打字，直接印出，並加上前綴
                    print(f"\r[{recv_time}] [Arduino 回傳]: {msg}\n> ", end="", flush=True)

        except serial.SerialException:
            print("\n[錯誤] 失去與 Arduino 的連線。")
            is_running = False
            break

        # 極短的休眠 (1毫秒)，防止這個迴圈吃滿 CPU 單核效能，同時維持低延遲
        time.sleep(0.001)


def main():
    global is_running

    print(f"正在嘗試連接 {PORT} (Baud: {BAUD_RATE})...")
    try:
        # timeout 設積極一點，配合 in_waiting 使用
        ser = serial.Serial(PORT, BAUD_RATE, timeout=0.01)
        time.sleep(2)  # 給予 Arduino 重置的緩衝時間 (多數 Arduino 連線時會重啟)
        ser.reset_input_buffer()  # 清空連線瞬間可能產生的亂碼
    except Exception as e:
        print(f"連線失敗，請確認 Arduino 是否接上且未被 IDE 佔用 COM 埠。\n錯誤訊息: {e}")
        return

    # 1. 紀錄開始連線的瞬間
    start_time = get_timestamp()
    log_data.append([start_time, "SYSTEM", f"已成功連接至 {PORT}"])
    print(f"[{start_time}] 連接成功！Log 紀錄已啟動。")
    print("--------------------------------------------------")
    print("請直接在下方輸入指令並按 Enter 送出。")
    print("輸入 'STOP' (全大寫) 將結束程式並儲存 CSV。")
    print("--------------------------------------------------")

    # 2. 啟動背景監聽執行緒
    listener_thread = threading.Thread(target=listen_to_arduino, args=(ser,), daemon=True)
    listener_thread.start()

    # 3. 主執行緒：處理使用者輸入
    try:
        while is_running:
            # 這裡會等待使用者輸入
            user_input = input("> ")

            # 檢查是否為終止指令
            if user_input == "STOP":
                stop_time = get_timestamp()
                log_data.append([stop_time, "SYSTEM", "使用者觸發 STOP 指令，結束紀錄。"])
                is_running = False
                break

            if user_input:
                send_time = get_timestamp()
                # 將輸入的字串加上換行符號送出 (Arduino 通常依賴 \n 來判斷指令結束)
                ser.write((user_input + '\n').encode('utf-8'))

                # 紀錄到 Log
                log_data.append([send_time, "TX (PC -> Arduino)", user_input])

    except KeyboardInterrupt:
        # 捕捉 Ctrl+C 強制結束
        is_running = False
        log_data.append([get_timestamp(), "SYSTEM", "使用者強制中斷 (Ctrl+C)"])

    # === 結束與儲存程序 ===
    print("\n正在安全關閉連線並儲存 CSV 檔案...")

    # 等待背景執行緒安全結束
    listener_thread.join(timeout=1.0)
    ser.close()

    # 以當下系統時間建立檔名
    filename = datetime.now().strftime("Arduino_Log_%Y%m%d_%H%M%S.csv")

    # 寫入 CSV (使用 utf-8-sig 確保 Excel 打開不會亂碼)
    with open(filename, mode='w', newline='', encoding='utf-8-sig') as f:
        writer = csv.writer(f)
        writer.writerow(["Timestamp (ms)", "Direction", "Message"])
        writer.writerows(log_data)

    print(f"✅ 儲存完畢！檔案名稱: {filename}")


if __name__ == "__main__":
    main()
import socket
import json
import time

# Cut-the-corners TCP Client:
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
s.connect(('localhost', 6000))

def send_req_json(m_band, prev_throughput, buf_occ, av_bitrates, current_time, chunk_arg, rebuff_time, pref_bitrate ):

    #pack message
    req = json.dumps({"Measured Bandwidth" : m_band,
                     "Previous Throughput" : prev_throughput,
                     "Buffer Occupancy" : buf_occ,
                     "Available Bitrates" : av_bitrates,
                     "Video Time" : current_time,
                     "Chunk" : chunk_arg,
                     "Rebuffering Time" : rebuff_time,
                     "Preferred Bitrate" : pref_bitrate,
                     "exit" : 0})
    req += '\n'

    s.sendall(req.encode())

    message = ""
    while True:
        messagepart = s.recv(2048).decode()
        if not messagepart:
            continue  # 没收到数据，继续等待
        message += messagepart
        if message and message[-1] == '\n':  # 先判断非空
            try:
                response = json.loads(message)
                return response["bitrate"]
            except Exception as e:
                print("JSON解析错误:", e)
                print("收到内容:", message)
                return None

def send_exit():
    req = json.dumps({"exit" : 1})
    req += '\n'
    s.sendall(req.encode())

if __name__ == "__main__":
    pass

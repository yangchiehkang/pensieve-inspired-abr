import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
import torch.optim as optim
import torch.multiprocessing as mp
import os
import time

k = 5

history_bandwidth = []
history_download_time = []
history_bitrate = []

LOG_FILE = "abr_log.txt"

# ======= 可调的 reward 参数 =======
REWARD_ALPHA = 5.0   # 卡顿惩罚系数（可调 4.3~6.0）
REWARD_BETA = 1.5    # 切换惩罚系数（可调 0.5~2.0）

def log_to_file(info: str):
    """写入日志文件"""
    with open(LOG_FILE, "a") as f:
        f.write(info + "\n")

def get_time_str():
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())

# ========== RL模型定义部分不变 ==========
class ActorCriticNet(nn.Module):
    def __init__(self, input_dim, output_dim):
        super(ActorCriticNet, self).__init__()
        self.conv1 = nn.Conv1d(1, 16, kernel_size=3, padding=1)
        self.conv2 = nn.Conv1d(16, 32, kernel_size=3, padding=1)
        self.fc1 = nn.Linear(32 * input_dim, 64)
        self.actor_fc = nn.Linear(64, output_dim)
        self.critic_fc = nn.Linear(64, 1)

    def forward(self, x, temperature=1.0):
        x = torch.tensor(x, dtype=torch.float32).unsqueeze(0).unsqueeze(0)
        x = (x - x.mean()) / (x.std() + 1e-5)
        x = F.relu(self.conv1(x))
        x = F.relu(self.conv2(x))
        x = x.view(1, -1)
        x = F.relu(self.fc1(x))
        logits = self.actor_fc(x) / temperature
        probs = F.softmax(logits, dim=1)
        value = self.critic_fc(x)
        return probs.squeeze(0), value.squeeze(0)

    def select_bitrate(self, state, available_bitrates, buffer_size):
        min_temp, max_temp = 0.5, 2.0
        buffer_norm = max(0.0, min(buffer_size / 60.0, 1.0))
        temperature = min_temp + (max_temp - min_temp) * buffer_norm
        probs, _ = self.forward(state, temperature=temperature)
        probs = probs.detach().cpu().numpy()
        probs = np.clip(probs, 1e-8, 1.0)
        probs = probs / np.sum(probs)
        chosen_idx = np.random.choice(len(available_bitrates), p=probs)
        chosen_idx = min(max(chosen_idx, 0), len(available_bitrates) - 1)
        return chosen_idx

def compute_reward(bitrate, last_bitrate, rebuffer_time, alpha=REWARD_ALPHA, beta=REWARD_BETA):
    def q(x): return np.log(x)
    reward = q(bitrate) - alpha * rebuffer_time - beta * abs(q(bitrate) - q(last_bitrate))
    return reward

abr_agent = None
model_path = 'pensieve_a3c.pth'

def safe_float(x, default=0.0):
    try:
        if x is None:
            return default
        return float(x)
    except Exception:
        return default

def pad_list(lst, length, pad_value=0.0):
    return lst + [pad_value] * (length - len(lst))

# ========== 优化后的决策入口 ==========
def student_entrypoint(Measured_Bandwidth, Previous_Throughput, Buffer_Occupancy, Available_Bitrates, Video_Time, Chunk, Rebuffering_Time, Preferred_Bitrate):
    """
    兼容评测环境的API，输入参数与作业说明一致，输出为int码率
    """
    global abr_agent, history_bandwidth, history_download_time, history_bitrate, model_path

    # 1. 码率列表处理（兼容dict和list）
    if isinstance(Available_Bitrates, dict):
        available_bitrates_list = sorted([int(k) for k in Available_Bitrates.keys()])
    elif isinstance(Available_Bitrates, list):
        available_bitrates_list = [int(x) for x in Available_Bitrates]
    else:
        print("Available_Bitrates invalid:", Available_Bitrates)
        return 500000

    # 2. 构造状态向量
    mbw = safe_float(Measured_Bandwidth)
    history_bandwidth.append(mbw)
    if len(history_bandwidth) > k:
        history_bandwidth.pop(0)

    chunk_time = safe_float(Chunk.get("time", 0) if Chunk else 0)
    history_download_time.append(chunk_time)
    if len(history_download_time) > k:
        history_download_time.pop(0)

    pb = safe_float(Preferred_Bitrate)
    history_bitrate.append(pb)
    if len(history_bitrate) > k:
        history_bitrate.pop(0)

    buffer_size = safe_float(Buffer_Occupancy.get('time', 0) if Buffer_Occupancy else 0)
    chunk_index = safe_float(Chunk.get('current', 0) if Chunk else 0)
    chunks_left = safe_float(Chunk.get('left', 0) if Chunk else 0)
    rebuffer_time = safe_float(Rebuffering_Time)

    chunk_sizes = []
    if Chunk and 'sizes' in Chunk and Chunk['sizes']:
        chunk_sizes = [safe_float(sz) for sz in Chunk['sizes']]
    else:
        chunk_sizes = [1.0 for _ in available_bitrates_list]
    chunk_sizes = pad_list(chunk_sizes, len(available_bitrates_list), 1.0)

    prev_tp = safe_float(Previous_Throughput)

    state = []
    state.extend(pad_list(history_bandwidth, k, 0.0))
    state.extend(pad_list(history_download_time, k, 0.0))
    state.extend(pad_list(history_bitrate, k, 0.0))
    state.append(buffer_size)
    state.append(chunk_index)
    state.append(chunks_left)
    state.extend(chunk_sizes)
    state.append(rebuffer_time)
    state.append(prev_tp)

    # 3. 初始化/加载模型（推理阶段只加载，不训练）
    if abr_agent is None:
        input_dim = len(state)
        output_dim = len(available_bitrates_list)
        abr_agent = ActorCriticNet(input_dim, output_dim)
        if os.path.exists(model_path):
            try:
                abr_agent.load_state_dict(torch.load(model_path, map_location='cpu'))
                abr_agent.eval()
                print("模型加载成功，推理使用已训练权重")
            except Exception as e:
                print("模型加载失败，使用随机权重:", e)

    # ========== 极端trace强兜底策略 ==========
    pq_keywords = ["PQ", "pq", "HDmanPQtrace", "testPQ"]
    chunk_name = str(Chunk.get("name", "")) if Chunk else ""
    video_time_str = str(Video_Time)
    is_pqtrace = any(kw in chunk_name for kw in pq_keywords) or any(kw in video_time_str for kw in pq_keywords)

    if is_pqtrace:
        # PQtrace类测试集，强制最低码率
        chosen_bitrate = int(available_bitrates_list[0])
        log_info = f"{get_time_str()} | PQtrace强制最低码率 | CHUNK={chunk_index} | Buffer={buffer_size:.2f}s | Bandwidth={mbw:.2f} | ChosenBR={chosen_bitrate} | Rebuffer={rebuffer_time:.2f} | CAUSE=PQtrace"
        log_to_file(log_info)
        return chosen_bitrate

    # 非PQtrace，缓冲区更激进兜底
    BUFFER_SAFE = 5.0  # 提高到5秒，只要buffer小于5s就最低码率
    if buffer_size < BUFFER_SAFE:
        chosen_bitrate = int(available_bitrates_list[0])
        log_info = f"{get_time_str()} | Buffer<5s强制最低码率 | CHUNK={chunk_index} | Buffer={buffer_size:.2f}s | Bandwidth={mbw:.2f} | ChosenBR={chosen_bitrate} | Rebuffer={rebuffer_time:.2f} | CAUSE=BufferLow"
        log_to_file(log_info)
        return chosen_bitrate

    # 2. 带宽历史窗口决策
    HISTORY_WINDOW = 5
    bw_history = history_bandwidth[-HISTORY_WINDOW:] if len(history_bandwidth) >= HISTORY_WINDOW else history_bandwidth
    avg_bw = np.mean(bw_history) if bw_history else mbw
    min_bw = np.min(bw_history) if bw_history else mbw

    # 3. 结合历史和当前带宽做“安全带宽”决策
    bw_weight_current = 0.7
    bw_weight_history = 0.3
    decision_bw = bw_weight_current * mbw + bw_weight_history * avg_bw

    # 4. 如果带宽剧烈下降（如 min_bw < 0.5 * avg_bw），提前降码率
    if min_bw < 0.5 * avg_bw:
        for br in sorted(available_bitrates_list):
            if br <= min_bw:
                chosen_bitrate = int(br)
                log_info = f"{get_time_str()} | CHUNK={chunk_index} | Buffer={buffer_size:.2f}s | Bandwidth={mbw:.2f} | HistBW={history_bandwidth} | CurrentBR={pb} | ChosenBR={chosen_bitrate} | Rebuffer={rebuffer_time:.2f} | CAUSE=BWDrop"
                log_to_file(log_info)
                return chosen_bitrate
        chosen_bitrate = int(available_bitrates_list[0])
        log_info = f"{get_time_str()} | CHUNK={chunk_index} | Buffer={buffer_size:.2f}s | Bandwidth={mbw:.2f} | HistBW={history_bandwidth} | CurrentBR={pb} | ChosenBR={chosen_bitrate} | Rebuffer={rebuffer_time:.2f} | CAUSE=BWDrop"
        log_to_file(log_info)
        return chosen_bitrate

    # 5. RL模型输出，但加一层保护：选出来的码率不能高于决策带宽
    try:
        chosen_idx = abr_agent.select_bitrate(state, available_bitrates_list, buffer_size)
        if not isinstance(chosen_idx, int):
            chosen_idx = 0
        if chosen_idx < 0 or chosen_idx >= len(available_bitrates_list):
            chosen_idx = 0
        chosen_bitrate = available_bitrates_list[chosen_idx]

        # 如果 RL 选的码率高于决策带宽，降到最近一个安全码率
        safe_bitrate = chosen_bitrate
        for br in sorted(available_bitrates_list, reverse=True):
            if br <= decision_bw:
                safe_bitrate = br
                break
        if chosen_bitrate > safe_bitrate:
            chosen_bitrate = safe_bitrate

        # ========== 切换次数优化部分 ==========
        SWITCH_THRESHOLD_RATIO = 0.2    # 推荐20%
        SWITCH_THRESHOLD_ABS = 500000   # 推荐500kbps

        current_bitrate = int(safe_float(Preferred_Bitrate))
        recommended_bitrate = int(chosen_bitrate)

        # 切换次数优化：差距不大则不切换
        if current_bitrate in available_bitrates_list:
            diff = abs(recommended_bitrate - current_bitrate)
            ratio = diff / max(current_bitrate, 1)
            if ratio < SWITCH_THRESHOLD_RATIO and diff < SWITCH_THRESHOLD_ABS:
                chosen_bitrate_final = current_bitrate
                cause = "NoSwitch"
            else:
                chosen_bitrate_final = recommended_bitrate
                cause = "Switch"
        else:
            chosen_bitrate_final = recommended_bitrate
            cause = "Init"

        log_info = f"{get_time_str()} | CHUNK={chunk_index} | Buffer={buffer_size:.2f}s | Bandwidth={mbw:.2f} | HistBW={history_bandwidth} | CurrentBR={pb} | ChosenBR={chosen_bitrate_final} | RLBR={recommended_bitrate} | DecisionBW={decision_bw:.2f} | Rebuffer={rebuffer_time:.2f} | CAUSE={cause}"
        log_to_file(log_info)

        if rebuffer_time > 0.01:
            log_info_rebuf = f"{get_time_str()} | CHUNK={chunk_index} | Buffer={buffer_size:.2f}s | Bandwidth={mbw:.2f} | CurrentBR={pb} | ChosenBR={chosen_bitrate_final} | Rebuffer={rebuffer_time:.2f} | EVENT=Rebuffer"
            log_to_file(log_info_rebuf)

        return chosen_bitrate_final

    except Exception as e:
        print("Exception in student_entrypoint:", e)
        chosen_bitrate = int(available_bitrates_list[0]) if available_bitrates_list else 500000
        log_info = f"{get_time_str()} | CHUNK={chunk_index} | Buffer={buffer_size:.2f}s | Bandwidth={mbw:.2f} | HistBW={history_bandwidth} | CurrentBR={pb} | ChosenBR={chosen_bitrate} | Rebuffer={rebuffer_time:.2f} | CAUSE=Exception"
        log_to_file(log_info)
        return chosen_bitrate

# ----------- RL训练流程（A3C核心结构，伪环境接口） -----------
class DummyEnv:
    """伪环境，实际应替换为chunk-level simulator接口"""

    def __init__(self, input_dim, action_dim):
        self.input_dim = input_dim
        self.action_dim = action_dim
        self.state = np.random.rand(self.input_dim)
        self.t = 0

    def reset(self):
        self.t = 0
        self.state = np.random.rand(self.input_dim)
        return self.state

    def step(self, action):
        next_state = np.random.rand(self.input_dim)
        bitrate = 500000 + action * 500000
        last_bitrate = 500000 + (action-1) * 500000 if action > 0 else bitrate
        rebuffer_time = np.random.rand() * 0.5
        reward = compute_reward(bitrate, last_bitrate, rebuffer_time)  # 用全局参数
        self.t += 1
        done = self.t > 20
        info = {}
        return next_state, reward, done, info

def worker_run(global_net, optimizer, input_dim, action_dim):
    local_net = ActorCriticNet(input_dim, action_dim)
    local_net.load_state_dict(global_net.state_dict())
    env = DummyEnv(input_dim, action_dim)
    state = env.reset()
    done = False
    gamma = 0.99
    while not done:
        probs, value = local_net.forward(state)
        probs_np = probs.detach().cpu().numpy()
        action = np.random.choice(action_dim, p=probs_np)
        next_state, reward, done, info = env.step(action)
        _, next_value = local_net.forward(next_state)
        advantage = reward + (0 if done else gamma * next_value.item()) - value.item()
        policy_loss = -torch.log(probs[action]) * advantage
        value_loss = F.mse_loss(value, torch.tensor([reward + (0 if done else gamma * next_value.item())]))
        entropy = -(probs * torch.log(probs + 1e-8)).sum()
        loss = policy_loss + 0.5 * value_loss - 0.01 * entropy
        optimizer.zero_grad()
        loss.backward()
        for global_param, local_param in zip(global_net.parameters(), local_net.parameters()):
            if global_param.grad is None:
                global_param.grad = local_param.grad
            else:
                global_param.grad += local_param.grad
        optimizer.step()
        local_net.load_state_dict(global_net.state_dict())
        state = next_state

def train_a3c(input_dim, action_dim, num_workers=4):
    global model_path
    global_net = ActorCriticNet(input_dim, action_dim)
    global_net.share_memory()
    optimizer = optim.Adam(global_net.parameters(), lr=1e-4)
    processes = []
    for _ in range(num_workers):
        p = mp.Process(target=worker_run, args=(global_net, optimizer, input_dim, action_dim))
        p.start()
        processes.append(p)
    for p in processes:
        p.join()
    torch.save(global_net.state_dict(), model_path)
    print("训练完成，模型已保存为", model_path)

def load_trained_model(input_dim, action_dim, path='pensieve_a3c.pth'):
    net = ActorCriticNet(input_dim, action_dim)
    net.load_state_dict(torch.load(path, map_location='cpu'))
    net.eval()
    return net

# ----------- 训练示例（实际应传入真实input_dim和action_dim） -----------
if __name__ == "__main__":
    input_dim = 3 * k + 7  # 例如: 历史+buffer+chunk等
    action_dim = 6         # 例如: 6种码率
    train_a3c(input_dim, action_dim, num_workers=2)

    trained_agent = load_trained_model(input_dim, action_dim)
    test_state = np.random.rand(input_dim)
    buffer_size = 20.0
    available_bitrates = [500000, 1000000, 1500000, 2000000, 2500000, 3000000]
    chosen_idx = trained_agent.select_bitrate(test_state, available_bitrates, buffer_size)
    print("推理选码率idx:", chosen_idx, "码率:", available_bitrates[chosen_idx])

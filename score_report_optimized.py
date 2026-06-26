import os
import time
import subprocess
import threading
import sys

def run_student_code():
    subprocess.run(['python', 'studentComm.py'])
    return

def read_previous_scores(filename="score_report.txt"):
    """读取旧评分结果，返回字典，便于对比"""
    old_scores = {}
    if not os.path.exists(filename):
        return old_scores
    with open(filename, "r", encoding="utf-8") as f:
        for line in f:
            if "|" in line and "测试集名称" not in line:
                parts = line.split("|")
                if len(parts) >= 6:
                    name = parts[1].strip()
                    score = parts[5].strip()
                    try:
                        score = float(score)
                    except:
                        continue
                    old_scores[name] = score
    return old_scores

def parse_simulator_output(output, testname):
    """
    解析仿真器输出，返回三项指标和分数
    """
    average_bitrate = None
    buffer_time = None
    switches = None

    try:
        outputlines = output.split('\n')
        sanitizedoutput = [line.strip() for line in outputlines if line.strip()]
        for line in sanitizedoutput:
            if "Average bitrate" in line:
                # 允许出现单位或多余字符
                try:
                    average_bitrate = float(line.split(':')[1].strip().split()[0])
                except Exception as e:
                    print(f"[ERROR] {testname} 平均码率解析失败: {e} | line: {line}")
            if "buffer time" in line:
                try:
                    buffer_time = float(line.split(':')[1].strip().split()[0])
                except Exception as e:
                    print(f"[ERROR] {testname} 卡顿时间解析失败: {e} | line: {line}")
            if "switches" in line:
                try:
                    switches = float(line.split(':')[1].strip().split()[0])
                except Exception as e:
                    print(f"[ERROR] {testname} 切换次数解析失败: {e} | line: {line}")

        if average_bitrate is None or buffer_time is None or switches is None:
            print(f"[ERROR] {testname} 解析仿真器输出缺失项: bitrate={average_bitrate}, buffer={buffer_time}, switches={switches}")
            return '-', '-', '-', 0

        # 分数计算公式
        buffer_penalty = pow((1 - (.05 * buffer_ratio)), buffer_time)
        switch_penalty = pow((1 - (.08 * switch_ratio)), switches)
        score = average_bitrate * buffer_penalty * switch_penalty
        return average_bitrate, buffer_time, switches, score

    except Exception as e:
        print(f"[ERROR] {testname} 解析仿真器输出异常: {e}")
        return '-', '-', '-', 0

if __name__ == "__main__":
    verboseflag = ""
    if "-v" in sys.argv or "--verbose" in sys.argv:
        verboseflag = "-v"

    switch_ratio = 1
    buffer_ratio = 1

    manifestfilename = 'manifest.json'
    tracefilename = 'trace.txt'

    # 收集所有结果用于汇总
    results = []

    # 读取旧评分，便于对比
    prev_scores = read_previous_scores()

    for testdir in os.listdir('./tests/'):
        testpath = "./tests/" + testdir + "/"
        manifestpath = testpath + manifestfilename
        tracepath = testpath + tracefilename

        print(f'正在测试：{testdir}')
        try:
            # 启动学生代码通信线程
            student_thread = threading.Thread(target=run_student_code)
            student_thread.start()
            time.sleep(1)

            # 运行仿真器并收集输出
            output = subprocess.run(
                ['python', 'simulator.py', tracepath, manifestpath, verboseflag],
                capture_output=True
            )
            student_thread.join()

            # 解析仿真器输出
            sim_output = output.stdout.decode('utf-8', errors='ignore')
            average_bitrate, buffer_time, switches, score = parse_simulator_output(sim_output, testdir)

        except Exception as e:
            print(f'[ERROR] 测试集 {testdir} 运行仿真器异常: {e}')
            average_bitrate, buffer_time, switches, score = '-', '-', '-', 0

        prev_score = prev_scores.get(testdir, "-")
        diff_score = round(score - prev_score, 2) if isinstance(prev_score, float) else "-"

        results.append({
            "name": testdir,
            "bitrate": average_bitrate if average_bitrate != '-' else "-",
            "buffer": buffer_time if buffer_time != '-' else "-",
            "switches": switches if switches != '-' else "-",
            "score": round(score, 2) if isinstance(score, float) or isinstance(score, int) else "-",
            "prev_score": prev_score,
            "diff": diff_score
        })

    # 汇总输出
    table_header = (
        "==================== 优化后评分报告 ====================\n"
        "| 测试集名称        | 平均码率    | 卡顿时间   | 切换次数 | 优化后分数 | 原分数   | 分数提升 |\n"
        "-----------------------------------------------------------\n"
    )

    table_rows = ""
    total_score = 0
    valid_count = 0

    for res in results:
        table_rows += f"| {res['name']:<15} | {res['bitrate']:<11} | {res['buffer']:<9} | {res['switches']:<9} | {res['score']:<10} | {res['prev_score']:<8} | {res['diff']:<8} |\n"
        if isinstance(res['score'], float) or isinstance(res['score'], int):
            total_score += res['score']
            valid_count += 1

    table_footer = "===========================================================\n"
    avg_score = round(total_score / valid_count, 2) if valid_count > 0 else 0

    summary = f"优化后平均分数：{avg_score}\n"

    # 输出到文件
    with open("score_report_optimized.txt", 'w', encoding='utf-8') as outfile:
        outfile.write(table_header)
        outfile.write(table_rows)
        outfile.write(table_footer)
        outfile.write(summary)

    # 也可以选择在终端打印
    print(table_header + table_rows + table_footer + summary)

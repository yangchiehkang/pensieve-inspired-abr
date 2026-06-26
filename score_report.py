import os
import time
import subprocess
import threading
import sys

def run_student_code():
    subprocess.run(['python', 'studentComm.py'])
    return

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

    for testdir in os.listdir('./tests/'):
        testpath = "./tests/" + testdir + "/"
        manifestpath = testpath + manifestfilename
        tracepath = testpath + tracefilename

        student_thread = threading.Thread(target=run_student_code)
        student_thread.start()
        time.sleep(1)

        output = subprocess.run(['python', 'simulator.py', tracepath, manifestpath, verboseflag], capture_output=True)
        student_thread.join()

        outputlines = output.stdout.decode('unicode_escape').split('\n')
        sanitizedoutput = [line.strip() for line in outputlines]

        average_bitrate = None
        buffer_time = None
        switches = None

        for line in sanitizedoutput:
            if "Average bitrate" in line:
                average_bitrate = float(line.split(':')[1])
            if "buffer time" in line:
                buffer_time = float(line.split(':')[1])
            if "switches" in line:
                switches = float(line.split(':')[1])

        score = None
        if switches is not None and buffer_time is not None and average_bitrate is not None:
            buffer_penalty = pow((1 - (.05 * buffer_ratio)), buffer_time)
            switch_penalty = pow((1 - (.08 * switch_ratio)), switches)
            score = average_bitrate * buffer_penalty * switch_penalty
        else:
            score = 0

        results.append({
            "name": testdir,
            "bitrate": average_bitrate if average_bitrate is not None else "-",
            "buffer": buffer_time if buffer_time is not None else "-",
            "switches": switches if switches is not None else "-",
            "score": round(score, 2) if score is not None else "-"
        })

    # 汇总输出
    table_header = (
        "-----------------------------------------------------------\n"
        "| 测试集名称        | 平均码率    | 卡顿时间   | 切换次数 | 分数     |\n"
        "-----------------------------------------------------------\n"
    )

    table_rows = ""
    total_score = 0
    valid_count = 0

    for res in results:
        table_rows += f"| {res['name']:<15} | {res['bitrate']:<11} | {res['buffer']:<9} | {res['switches']:<9} | {res['score']:<8} |\n"
        if isinstance(res['score'], float) or isinstance(res['score'], int):
            total_score += res['score']
            valid_count += 1

    table_footer = "-----------------------------------------------------------\n"
    avg_score = round(total_score / valid_count, 2) if valid_count > 0 else 0

    summary = f"平均分数：{avg_score}\n"

    # 输出到文件
    with open("score_report.txt", 'w', encoding='utf-8') as outfile:
        outfile.write(table_header)
        outfile.write(table_rows)
        outfile.write(table_footer)
        outfile.write(summary)

    # 也可以选择在终端打印
    print(table_header + table_rows + table_footer + summary)

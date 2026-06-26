import sys
import json
from Classes import SimBuffer, NetworkTrace, Scorecard, simulator_comm

verbose = False

def loadtrace(tracefile):
    with open(tracefile, 'r', encoding='utf-8') as infile:
        lines = infile.readlines()
    tracelog = []
    for line in lines:
        splitline = line.split(' ')
        if len(splitline) > 1:
            try:
                tracelog.append((float(splitline[0]), float(splitline[1])))
            except ValueError as e:
                print(f"[ERROR] Trace file malformed: {e}")
    trace = NetworkTrace.NetworkTrace(tracelog)
    return trace

def loadmanifest(manifestfile):
    with open(manifestfile, 'r', encoding='utf-8') as infile:
        lines = infile.read()
    manifest = json.loads(lines)
    return manifest

def prep_bitrates(available_rates, chunk):
    rates = dict(map(lambda x, y: (x, y), available_rates, chunk))
    return rates

def prep_chunk(chunks_rem, manifest, chunk_num):
    params = {
        "left": chunks_rem,
        "time": manifest["Chunk_Time"],
        "current": chunk_num
    }
    return params

if __name__ == "__main__":
    if "-v" in sys.argv or "--verbose" in sys.argv:
        verbose = True

    try:
        trace = loadtrace(sys.argv[1])
        manifest = loadmanifest(sys.argv[2])
    except Exception as e:
        print(f"[ERROR] Failed to load trace or manifest: {e}")
        sys.exit(1)

    logger = Scorecard.Scorecard(1, 1, 1)
    buffer = SimBuffer.SimBuffer(manifest["Buffer_Size"])

    chunks_remaining = manifest["Chunk_Count"]
    current_time = 0
    prev_throughput = 0
    rebuff_time = 0
    pref_bitrate = manifest["Preferred_Bitrate"]

    chunk_list = [(key, value) for key, value in manifest["Chunks"].items()]
    chunk_iter = iter(chunk_list)
    chunknum, chunk = next(chunk_iter, (None, None))

    while chunk is not None:
        try:
            m_band = trace.get_current_timesegment(current_time)[1]
            buf_occ = buffer.get_student_params()
            av_bitrates = prep_bitrates(manifest["Available_Bitrates"], chunk)
            chunk_arg = prep_chunk(chunks_remaining, manifest, chunknum)

            # send info to student, get response
            chosen_bitrate = simulator_comm.send_req_json(
                m_band, prev_throughput, buf_occ, av_bitrates,
                current_time, chunk_arg, rebuff_time, pref_bitrate
            )

            # bad response checking, ensure chunk fits in buffer
            try:
                stu_chunk_size = av_bitrates[int(chosen_bitrate)]
            except KeyError:
                print(f"[ERROR] Invalid bitrate returned: {chosen_bitrate}, skipping chunk {chunknum}")
                chunknum, chunk = next(chunk_iter, (None, None))
                continue

            if stu_chunk_size > buffer.available_space():
                # chunk chosen does not fit in buffer, wait .5s and resend request
                buffer_time = buffer.burn_time(.5)
                current_time += .5
                print(f"[WARN] Chunk {chunknum} too big for buffer, waiting 0.5s, buffer_time={buffer_time}")
                continue

            logger.log_bitrate_choice(current_time, chunknum, (chosen_bitrate, stu_chunk_size))

            # simulate download and playback
            time_elapsed = trace.simulate_download_from_time(current_time, stu_chunk_size)
            time_elapsed = round(time_elapsed, 3)
            rebuff_time = buffer.sim_chunk_download(stu_chunk_size, chunk_arg["time"], time_elapsed)

            prev_throughput = (stu_chunk_size * 8) / time_elapsed if time_elapsed > 0 else 0
            current_time += time_elapsed
            chunks_remaining -= 1

            logger.log_rebuffer(current_time - rebuff_time, rebuff_time)

        except Exception as e:
            print(f"[ERROR] Exception in main loop at chunk {chunknum}: {e}")
            # 跳过当前 chunk，继续下一个
            chunknum, chunk = next(chunk_iter, (None, None))
            continue

        # get next chunk
        chunknum, chunk = next(chunk_iter, (None, None))

    # cleanup and return
    simulator_comm.send_exit()

    try:
        if verbose:
            logger.output_verbose()
        else:
            logger.output_results()
    except Exception as e:
        print(f"[ERROR] Failed to output results: {e}")

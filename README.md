# Pensieve-Inspired Adaptive Bitrate Streaming

A lightweight simulator-based implementation of an adaptive bitrate streaming algorithm inspired by Pensieve.

This project explores how a video player can dynamically select video bitrates under changing network conditions. The algorithm makes bitrate decisions based on estimated bandwidth, playback buffer status, chunk information, and quality-of-experience trade-offs.

---

## Overview

Adaptive Bitrate Streaming, or ABR, is used in HTTP video streaming systems to improve playback quality under variable network bandwidth.

The goal of this project is to select an appropriate bitrate for each video chunk to achieve better overall Quality of Experience, or QoE.

The ABR controller considers:

- Estimated network bandwidth
- Current playback buffer occupancy
- Available video bitrates
- Expected download time
- Rebuffering risk
- Bitrate smoothness
- Playback quality reward

The implementation is tested in a local simulator that provides network traces, video manifests, buffer states, and scoring results.

---

## Features

- Simulator-based adaptive bitrate testing
- Pensieve-inspired ABR decision logic
- Bandwidth-aware bitrate selection
- Buffer-aware rebuffering avoidance
- QoE-oriented bitrate control
- Support for multiple network traces and manifest files
- Local grading and score reporting
- Simple Python implementation with no complex external services

---

## Repository Structure

```text
.
├── Classes/
│   ├── NetworkTrace.py
│   ├── Scorecard.py
│   ├── SimBuffer.py
│   └── simulator_comm.py
│
├── inputs/
│   ├── manifestHD.json
│   ├── manifestPQ.json
│   ├── traceHD.txt
│   ├── tracePQ.txt
│   └── ...
│
├── tests/
│   ├── testALThard/
│   ├── testALTsoft/
│   ├── testHD/
│   ├── testHDmanPQtrace/
│   └── testPQ/
│
├── grader.py
├── rand_sizes.py
├── simulator.py
├── studentComm.py
├── studentcode_pensieve.py
├── score_report.py
├── req.txt
└── README.md
```

---

## Algorithm Idea

The ABR algorithm uses a practical heuristic inspired by Pensieve-style QoE optimization.

For each video chunk, the algorithm estimates whether each available bitrate can be safely downloaded before the buffer runs out. It then selects a bitrate that balances video quality, rebuffering avoidance, and smoothness.

The decision process includes:

1. Estimate recent bandwidth from previous downloads.
2. Predict download time for each candidate bitrate.
3. Check current buffer level and rebuffering risk.
4. Penalize large bitrate switches.
5. Select the bitrate with the best expected QoE score.

This makes the algorithm more stable than a purely bandwidth-based method and more responsive than a fixed bitrate strategy.

---

## Quality of Experience Objective

The simulator evaluates streaming performance using a QoE-oriented score.

The main factors are:

- Higher selected bitrate is better.
- Rebuffering is heavily penalized.
- Frequent quality switches are penalized.
- Smooth playback is preferred.
- Stable adaptation under changing bandwidth is important.

The algorithm aims to maximize overall QoE rather than simply choosing the highest possible bitrate.

---

## How to Run

Start the student communication process in one terminal:

```bash
python studentComm.py
```

Then run the simulator in another terminal:

```bash
python simulator.py inputs/traceHD.txt inputs/manifestHD.json
```

The simulator will execute the ABR algorithm and print playback results.

---

## Run the Grader

To evaluate the algorithm across multiple test cases, run:

```bash
python grader.py
```

The grader reads test cases from the `tests/` directory and outputs the final score and related metrics.

Each test case should follow this structure:

```text
tests/
└── test_name/
    ├── manifest.json
    └── trace.txt
```

---

## Example Inputs

A trace file describes network bandwidth changes over video time:

```text
0 1000000
10 5000000
20 2000000
30 800000
40 1000000
50 5000000
```

A manifest file describes:

- Video duration
- Number of chunks
- Chunk duration
- Buffer size
- Available bitrates
- Per-chunk sizes for each bitrate

---

## Requirements

The project is implemented in Python.

To install dependencies:

```bash
pip install -r requirements.txt
```

If using the provided environment file:

```bash
pip install -r req.txt
```

---

## Notes

This repository focuses on ABR algorithm design and simulator-based evaluation.

It does not include large datasets, external video files, or copyrighted paper PDFs. The simulator uses trace files and manifest files to reproduce different network and streaming scenarios.

---

## References

- Pensieve: Neural Adaptive Video Streaming with Pensieve, SIGCOMM 2017
- BOLA: Near-Optimal Bitrate Adaptation for Online Videos
- Buffer-Based Rate Adaptation for HTTP Video Streaming
- Adaptive Bitrate Streaming survey papers and practical HTTP streaming systems

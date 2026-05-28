"""
QPU Demo: 5-qubit Bell-style GHZ state on Garnet via AWS Braket.

Builds a GHZ entangled state across 5 qubits (the multi-qubit generalization
of a Bell state), submits it to the Garnet QPU, polls until completion, and
prints the measurement histogram.

NOTE: "Garnet" on AWS Braket is IQM's superconducting QPU
(arn: arn:aws:braket:eu-north-1::device/qpu/iqm/Garnet), not IonQ.
For an IonQ device, pass --ionq to use IonQ Forte-1 instead.

Usage:
    python demos/qpu_demo.py [--shots N] [--simulator]

Requires AWS credentials with Braket access. Use --simulator to dry-run on SV1.
"""
from __future__ import annotations

import argparse
import sys
import time
from collections import Counter

try:
    from braket.aws import AwsDevice
    from braket.circuits import Circuit
except ImportError:
    print("ERROR: amazon-braket-sdk not installed.\n  pip install amazon-braket-sdk", file=sys.stderr)
    sys.exit(1)


# Device ARNs
IONQ_GARNET = "arn:aws:braket:eu-north-1::device/qpu/iqm/Garnet"  # IQM Garnet
IONQ_FORTE = "arn:aws:braket:us-east-1::device/qpu/ionq/Forte-1"
SV1 = "arn:aws:braket:::device/quantum-simulator/amazon/sv1"


def build_ghz_circuit(n_qubits: int = 5) -> Circuit:
    """Build an n-qubit GHZ state: H on q0, then CNOT chain."""
    circuit = Circuit()
    circuit.h(0)
    for q in range(n_qubits - 1):
        circuit.cnot(q, q + 1)
    return circuit


def submit_and_wait(device: AwsDevice, circuit: Circuit, shots: int, poll_s: float = 5.0):
    """Submit circuit and poll until task completes."""
    print(f"Submitting circuit to {device.name} ({shots} shots)...")
    task = device.run(circuit, shots=shots)
    task_id = task.id
    print(f"Task ID: {task_id}")

    while True:
        state = task.state()
        print(f"  state={state}")
        if state in ("COMPLETED", "FAILED", "CANCELLED"):
            break
        time.sleep(poll_s)

    if state != "COMPLETED":
        raise RuntimeError(f"Task ended with state={state}")
    return task.result()


def print_histogram(measurements) -> None:
    """Print a sorted histogram of bitstring measurement outcomes."""
    bitstrings = ["".join(str(b) for b in row) for row in measurements]
    counts = Counter(bitstrings)
    total = sum(counts.values())

    print("\nMeasurement histogram")
    print("=" * 40)
    for bits, n in sorted(counts.items(), key=lambda kv: -kv[1]):
        prob = n / total
        bar = "█" * int(prob * 40)
        print(f"  |{bits}⟩  {n:5d}  {prob:6.2%}  {bar}")
    print("=" * 40)
    print(f"Total shots: {total}")
    # GHZ state should concentrate on |00000⟩ and |11111⟩
    ideal = counts.get("00000", 0) + counts.get("11111", 0)
    print(f"GHZ fidelity proxy (|00000⟩+|11111⟩ frac): {ideal/total:.2%}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--shots", type=int, default=1000)
    parser.add_argument("--simulator", action="store_true", help="Use SV1 simulator instead of QPU")
    parser.add_argument("--ionq", action="store_true", help="Use IonQ Forte-1 instead of IQM Garnet")
    parser.add_argument("--qubits", type=int, default=5)
    args = parser.parse_args()

    circuit = build_ghz_circuit(args.qubits)
    print("Circuit:")
    print(circuit)

    if args.simulator:
        device_arn = SV1
    elif args.ionq:
        device_arn = IONQ_FORTE
    else:
        device_arn = IONQ_GARNET  # IQM Garnet
    device = AwsDevice(device_arn)

    result = submit_and_wait(device, circuit, args.shots)
    print_histogram(result.measurements)
    return 0


if __name__ == "__main__":
    sys.exit(main())

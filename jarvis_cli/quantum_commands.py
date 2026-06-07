"""
Quantum debugging and device optimization commands for jarvis-cli.

Integrates:
- quantum-bug-hunter (test prioritization via QuEra Aquila MIS)
- quantum-device-compat (responsive layout optimization)

Commands:
- jarvis --quantum-test <project_path> [--qpu] [--max-select N]
- jarvis --quantum-device <frontend_path> [--qpu] [--config file.json]
"""

import sys
import json
from pathlib import Path

# Color codes (matching main.py style)
CYAN = "\033[96m"
YELLOW = "\033[93m"
GREEN = "\033[92m"
RED = "\033[91m"
DIM = "\033[2m"
RESET = "\033[0m"


def quantum_test_prioritize_cli(project_path: str, use_qpu: bool = False, max_select: int = 5):
    """
    Run quantum-bug-hunter test prioritization.
    
    Args:
        project_path: Path to Python project with pytest tests
        use_qpu: Use QuEra Aquila QPU (~$2.60) vs local simulator (free)
        max_select: Number of tests to prioritize (default: 5)
    """
    print(f"\n  {CYAN}═══════════════════════════════════════════════════{RESET}")
    print(f"  {CYAN}🔬 QUANTUM TEST PRIORITIZATION{RESET}")
    print(f"  {CYAN}═══════════════════════════════════════════════════{RESET}\n")
    
    print(f"  Project:      {project_path}")
    print(f"  Device:       {'QuEra Aquila QPU (256 qubits)' if use_qpu else 'Local Simulator'}")
    print(f"  Max select:   {max_select} tests")
    print(f"  Estimated cost: {'$2.60' if use_qpu else '$0.00'}\n")
    
    # Import quantum-bug-hunter
    try:
        qbh_path = Path.home() / "repos" / "quantum-bug-hunter"
        if str(qbh_path) not in sys.path:
            sys.path.insert(0, str(qbh_path))
        
        from quantum_bug_hunter.collect_coverage import run_pytest_coverage, load_coverage_json
        from quantum_bug_hunter.prioritizer import prioritize_tests
        import numpy as np
    except ImportError as e:
        print(f"  {RED}❌ Error: quantum-bug-hunter not found{RESET}")
        print(f"  {DIM}Install: pip install -e ~/repos/quantum-bug-hunter{RESET}")
        print(f"  {DIM}Error details: {e}{RESET}")
        return
    
    # Run coverage collection
    print(f"  {DIM}Collecting test coverage...{RESET}")
    try:
        project_dir = Path(project_path)
        coverage_data = run_pytest_coverage(project_dir)
        
        # Load coverage matrix
        coverage_json_path = project_dir / "coverage.json"
        if not coverage_json_path.exists():
            print(f"  {RED}❌ No coverage.json found. Run: cd {project_path} && pytest --cov --cov-report=json{RESET}")
            return
        
        test_names, coverage_matrix, failure_history = load_coverage_json(str(coverage_json_path))
        
        if len(test_names) == 0:
            print(f"  {RED}❌ No tests found in coverage data{RESET}")
            return
        
        print(f"  {GREEN}✓{RESET} Collected coverage: {len(test_names)} tests, {coverage_matrix.shape[1]} code paths\n")
        
    except Exception as e:
        print(f"\n  {RED}❌ Coverage collection failed: {e}{RESET}")
        import traceback
        print(f"  {DIM}{traceback.format_exc()}{RESET}")
        return
    
    # Run quantum prioritization
    print(f"  {DIM}Running quantum prioritization...{RESET}")
    try:
        results = prioritize_tests(
            test_names=test_names,
            coverage_matrix=coverage_matrix,
            failure_history=failure_history,
            max_select=max_select,
            use_qpu=use_qpu,
        )
    except Exception as e:
        print(f"\n  {RED}❌ Prioritization failed: {e}{RESET}")
        import traceback
        print(f"  {DIM}{traceback.format_exc()}{RESET}")
        return
    
    # Display results
    print(f"\n  {GREEN}✅ Prioritization complete!{RESET}\n")
    print(f"  {CYAN}PRIORITY TESTS (run these first):{RESET}\n")
    
    selected_count = 0
    for i, test in enumerate(results, 1):
        if test.get("selected"):
            selected_count += 1
            score = test.get("score", 0)
            name = test.get("test_name", "unknown")
            coverage = test.get("coverage_score", 0)
            failure = test.get("failure_score", 0)
            print(f"    {selected_count}. {name:60s}")
            print(f"       score={score:.3f} (coverage={coverage:.2f}, failure_risk={failure:.2f})")
    
    # Show pytest command
    selected_tests = [t["test_name"] for t in results if t.get("selected")]
    if selected_tests:
        # Extract just the test function names
        test_funcs = [t.split("::")[-1] if "::" in t else t for t in selected_tests]
        pytest_cmd = f'pytest -xvs -k "{" or ".join(test_funcs)}"'
        print(f"\n  {DIM}Run priority tests with:{RESET}")
        print(f"  {CYAN}{pytest_cmd}{RESET}\n")
    
    # Show cost
    if use_qpu:
        print(f"  {DIM}QPU cost: $2.60{RESET}")
    
    # Save results
    output_file = Path(project_path) / ".quantum_test_history.json"
    try:
        output_data = {
            "prioritized_tests": results,
            "n_selected": selected_count,
            "device": "QuEra Aquila QPU" if use_qpu else "LocalSimulator",
        }
        with output_file.open("w") as f:
            json.dump(output_data, f, indent=2)
        print(f"  {DIM}Results saved to: {output_file}{RESET}")
    except Exception as e:
        print(f"  {YELLOW}⚠️  Could not save results: {e}{RESET}")


def quantum_device_compat_cli(
    frontend_path: str,
    use_qpu: bool = False,
    component_config: str = None
):
    """
    Run quantum-device-compat responsive layout optimization.
    
    Args:
        frontend_path: Path to React/Next.js/Vue frontend project
        use_qpu: Use QuEra Aquila QPU (~$18 for 6 devices) vs classical sim (free)
        component_config: Optional JSON config for manual component overrides
    """
    print(f"\n  {CYAN}═══════════════════════════════════════════════════{RESET}")
    print(f"  {CYAN}📱 QUANTUM DEVICE COMPATIBILITY OPTIMIZATION{RESET}")
    print(f"  {CYAN}═══════════════════════════════════════════════════{RESET}\n")
    
    print(f"  Frontend:     {frontend_path}")
    print(f"  Device:       {'QuEra Aquila QPU (256 qubits)' if use_qpu else 'Classical MIS Simulation'}")
    if component_config:
        print(f"  Config:       {component_config}")
    else:
        print(f"  Extraction:   Auto-detect from React/Next.js files")
    print(f"  Estimated cost: {'~$18.00 (6 devices × 200 shots × $0.015/shot)' if use_qpu else '$0.00'}\n")
    
    # Import quantum-device-compat
    try:
        qdc_path = Path.home() / "repos" / "quantum-device-compat"
        if str(qdc_path) not in sys.path:
            sys.path.insert(0, str(qdc_path))
        
        from quantum_device_compat.auto_extract import extract_components_from_project
        from quantum_device_compat.nodesbio_integration import run_optimization
    except ImportError as e:
        print(f"  {RED}❌ Error: quantum-device-compat not found{RESET}")
        print(f"  {DIM}Install: pip install -e ~/repos/quantum-device-compat{RESET}")
        print(f"  {DIM}Error details: {e}{RESET}")
        return
    
    # Extract components
    print(f"  {DIM}Extracting components from {frontend_path}...{RESET}")
    try:
        components = extract_components_from_project(
            Path(frontend_path),
            config_path=Path(component_config) if component_config else None
        )
        print(f"  {GREEN}✓{RESET} Found {len(components)} components\n")
    except Exception as e:
        print(f"\n  {RED}❌ Component extraction failed: {e}{RESET}")
        import traceback
        print(f"  {DIM}{traceback.format_exc()}{RESET}")
        return
    
    # Show extracted components
    print(f"  {CYAN}Extracted Components:{RESET}\n")
    for i, comp in enumerate(components[:10], 1):  # Show first 10
        print(f"    {i}. {comp.id:30s} {comp.min_width}×{comp.min_height}px  priority={comp.priority:.2f}")
    if len(components) > 10:
        print(f"    {DIM}... and {len(components) - 10} more{RESET}\n")
    
    # Run optimization
    print(f"\n  {DIM}Running quantum optimization...{RESET}")
    try:
        # TODO: Pass extracted components to run_optimization
        # For now, run_optimization uses hardcoded NODESBIO_COMPONENTS
        config = run_optimization(local=not use_qpu, shots=200)
    except Exception as e:
        print(f"\n  {RED}❌ Optimization failed: {e}{RESET}")
        import traceback
        print(f"  {DIM}{traceback.format_exc()}{RESET}")
        return
    
    # Display results
    print(f"\n  {GREEN}✅ Optimization complete!{RESET}\n")
    print(f"  {CYAN}OPTIMAL LAYOUTS:{RESET}\n")
    
    for device_name, layout in config.layouts.items():
        print(f"  {device_name}:")
        print(f"    Score: {layout.score:.2f}")
        print(f"    Visible:   {', '.join([c.id for c in layout.components if c.visible][:5])}")
        print(f"    Collapsed: {', '.join([c.id for c in layout.components if c.collapsed][:5])}")
        print()
    
    # Save CSS config
    css_output = Path(frontend_path) / "quantum-layout.css"
    try:
        css_config = config.to_css_config()
        with css_output.open("w") as f:
            f.write(css_config)
        print(f"  {GREEN}✓{RESET} CSS saved to: {css_output}")
    except Exception as e:
        print(f"  {YELLOW}⚠️  Could not save CSS: {e}{RESET}")
    
    # Show cost
    if use_qpu:
        print(f"\n  {DIM}QPU cost: ~$18.00 (6 devices × 200 shots each){RESET}")


if __name__ == "__main__":
    # Test harness
    import sys
    
    if len(sys.argv) < 3:
        print("Usage:")
        print("  python quantum_commands.py test <project_path> [--qpu]")
        print("  python quantum_commands.py device <frontend_path> [--qpu]")
        sys.exit(1)
    
    command = sys.argv[1]
    path = sys.argv[2]
    use_qpu = "--qpu" in sys.argv
    
    if command == "test":
        quantum_test_prioritize_cli(path, use_qpu=use_qpu)
    elif command == "device":
        quantum_device_compat_cli(path, use_qpu=use_qpu)
    else:
        print(f"Unknown command: {command}")
        sys.exit(1)

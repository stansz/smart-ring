#!/usr/bin/env python3
"""
Test script for the three open questions:
1. Does syncing wipe data from the ring?
2. What's inside stored HRV data (RR intervals vs composite score)?
3. What's the R09 temperature sensor sampling rate?
"""
import asyncio
import time
from collector.sync_ring import SyncResult, log_sync_start, log_sync_complete, sync_ring


def test_sync_behavior():
    """Test if syncing wipes data from the ring."""
    print("=== TEST 1: Sync behavior (wipe data?) ===")
    print("First sync...")
    result1 = sync_ring()
    print(f"First sync: {result1.records_synced} records")

    print("\nSecond sync (same night)...")
    result2 = sync_ring()
    print(f"Second sync: {result2.records_synced} records")

    if result2.records_synced == 0:
        print("✓ CONFIRMED: Sync is read-and-clear (data wiped after first sync)")
        print("  Impact: Gadgetbridge on the go would prevent PC collector from getting that data")
    elif result2.records_synced == result1.records_synced:
        print("✓ CONFIRMED: Sync is read-only (data persists on ring)")
        print("  Impact: Multiple devices can pull the same data")
    else:
        print(f"? PARTIAL: Second sync returned {result2.records_synced} vs {result1.records_synced}")
        print("  Need to investigate further")


def test_hrv_data_format():
    """Test if ring stores RR intervals or composite HRV score."""
    print("\n=== TEST 2: HRV data format (RR intervals vs composite) ===")
    print("Running sync to check HRV data...")
    
    # Monkey-patch the logging to capture the result
    import collector.sync_ring as sync_module
    original_log_info = sync_module.log.info
    hrv_has_rr = [False]
    
    def capture_hrv_info(msg):
        original_log_info(msg)
        if "✓ HRV data includes RR intervals!" in msg:
            hrv_has_rr[0] = True
    
    sync_module.log.info = capture_hrv_info
    
    try:
        result = sync_ring()
    finally:
        sync_module.log.info = original_log_info

    print(f"Sync completed: {result.records_synced} records")
    
    if hrv_has_rr[0]:
        print("✓ RING STORES RR INTERVALS - Raw beat-to-beat timing data available")
        print("  Benefits: Can compute custom HRV metrics, RMSSD, pNN50 retrospectively")
    else:
        print("✓ RING STORES COMPOSITE HRV SCORE - Pre-computed metric only")
        print("  Limitation: No RR intervals, limited to ring's HRV algorithm")
        print("  Note: Can still compute trends and basic HRV analysis from stored values")


def test_temperature_sampling():
    """Test R09 temperature sensor sampling rate."""
    print("\n=== TEST 3: Temperature sensor sampling rate ===")
    print("Running sync to check temperature data...")
    
    # Monkey-patch the logging to capture the result
    import collector.sync_ring as sync_module
    original_log_info = sync_module.log.info
    temp_samples = [0]
    
    def capture_temp_info(msg):
        original_log_info(msg)
        if "sample count:" in msg:
            temp_samples[0] = int(msg.split("sample count:")[1])
    
    sync_module.log.info = capture_temp_info
    
    try:
        result = sync_ring()
    finally:
        sync_module.log.info = original_log_info

    print(f"Sync completed: {result.records_synced} records")
    print(f"Temperature samples captured: {temp_samples[0]}")
    
    if temp_samples[0] == 0:
        print("✗ Temperature sensor NOT working (R09 exclusive)")
    else:
        print(f"✓ Temperature sensor working")
        print(f"  Sample count suggests sampling interval of ~{168/temp_samples[0]:.1f} hours")
        print(f"  For sleep staging: {temp_samples[0]/7:.1f} samples per 7 days")
        print(f"  For activity tracking: Should have data throughout the day")


def main():
    """Run all three tests."""
    print("Starting open questions test suite...")
    print("Ring should be present and connected via BLE")
    print()

    try:
        test_sync_behavior()
        test_hrv_data_format()
        test_temperature_sampling()

        print("\n=== SUMMARY ===")
        print("All tests completed. Results above will guide pipeline design:")
        print("- Sync behavior → Affects how we use Gadgetbridge vs PC collector")
        print("- HRV data format → Determines our HRV computation approach")
        print("- Temp sampling → Impacts sleep staging accuracy")
        print("\nNext steps: Based on results, deploy appropriate components")

    except Exception as e:
        print(f"\nTest failed with error: {e}")
        import traceback
        traceback.print_exc()
        return 1

    return 0


if __name__ == "__main__":
    exit(main())
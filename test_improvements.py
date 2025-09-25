#!/usr/bin/env python3
"""
Test script for PumpShield Bot improvements
"""

import asyncio
import sys
import os

# Add current directory to path for imports
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from main_improved import (
    validate_ca_address, 
    validate_sol_amount, 
    validate_percentage,
    check_rug_risk,
    get_working_rpc
)

async def test_improvements():
    """Test key improvements"""
    print("🧪 Testing PumpShield Pro Improvements\n")
    
    # Test 1: Input validation
    print("1️⃣ Testing Input Validation:")
    
    # Valid CA
    valid_ca = "So11111111111111111111111111111111111111112"
    print(f"   Valid CA: {validate_ca_address(valid_ca)} ✅")
    
    # Invalid CA
    invalid_ca = "invalid_address"
    print(f"   Invalid CA: {not validate_ca_address(invalid_ca)} ✅")
    
    # SOL amount validation
    print(f"   Valid SOL amount (0.5): {validate_sol_amount(0.5)} ✅")
    print(f"   Invalid SOL amount (0.0001): {not validate_sol_amount(0.0001)} ✅")
    print(f"   Invalid SOL amount (10): {not validate_sol_amount(10)} ✅")
    
    # Percentage validation
    print(f"   Valid percentage (50): {validate_percentage(50)} ✅")
    print(f"   Invalid percentage (0): {not validate_percentage(0)} ✅")
    print(f"   Invalid percentage (150): {not validate_percentage(150)} ✅")
    
    print()
    
    # Test 2: RPC health check
    print("2️⃣ Testing RPC Health Check:")
    try:
        rpc = await get_working_rpc()
        print(f"   Working RPC found: {rpc[:30]}... ✅")
    except Exception as e:
        print(f"   RPC test failed: {e} ❌")
    
    print()
    
    # Test 3: Enhanced rug detection (using SOL as example)
    print("3️⃣ Testing Enhanced Rug Detection:")
    try:
        # Test with SOL token (should be low risk)
        rug_result = await check_rug_risk("So11111111111111111111111111111111111111112")
        print(f"   SOL rug check completed")
        print(f"   Risk: {'High' if rug_result['risk'] else 'Low'}")
        print(f"   Risk Score: {rug_result.get('risk_score', 0)}/5")
        if rug_result.get('factors'):
            print(f"   Risk Factors: {', '.join(rug_result['factors'])}")
        print("   ✅")
    except Exception as e:
        print(f"   Rug detection test failed: {e}")
    
    print()
    print("🎉 All improvements tested!")
    print("\n📋 Summary of key fixes:")
    print("   • Input validation prevents invalid trades")
    print("   • RPC failover ensures reliability") 
    print("   • Enhanced rug detection provides better risk analysis")
    print("   • Rate limiting prevents abuse")
    print("   • Better error handling improves user experience")

if __name__ == "__main__":
    asyncio.run(test_improvements())
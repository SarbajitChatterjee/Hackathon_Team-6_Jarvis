import requests
import json
import time

# Configuration
WEBHOOK_URL = "https://unisaarland.app.n8n.cloud/webhook-test/start-analysis"
FASTAPI_URL = "http://63.179.141.203:8002"
REQUEST_ID = "b3835f83-6dc0-4141-85c6-ec5f5aba5c12"

print("=" * 70)
print("Starting Analysis Workflow")
print("=" * 70)

# Step 1: Trigger the webhook
print(f"\n[1/3] Triggering n8n workflow...")
print(f"Request ID: {REQUEST_ID}")

try:
    response = requests.post(
        WEBHOOK_URL,
        json={"request_id": REQUEST_ID},
        headers={"Content-Type": "application/json"},
        timeout=10  # Now webhook responds immediately, so 10s is plenty
    )
    
    if response.status_code == 200:
        result = response.json()
        print(f"✅ Response: {json.dumps(result, indent=2)}")
        
        # Extract status URL if provided
        status_url = result.get('check_status_at', f"{FASTAPI_URL}/api/v1/status/{REQUEST_ID}")
    else:
        print(f"❌ Error {response.status_code}: {response.text}")
        exit(1)
        
except requests.exceptions.Timeout:
    print("❌ Webhook timed out - check n8n configuration!")
    print("   Make sure you added 'Respond to Webhook' node right after Webhook Trigger")
    exit(1)
except requests.exceptions.RequestException as e:
    print(f"❌ Request failed: {e}")
    exit(1)

# Step 2: Wait and poll for completion
print(f"\n[2/3] Waiting for analysis to complete...")
print(f"Status URL: {status_url}")

time.sleep(8)  # Give it a moment to upload data and start processing

max_attempts = 30  # 30 attempts * 3 seconds = 90 seconds max
for attempt in range(1, max_attempts + 1):
    try:
        status_response = requests.get(status_url, timeout=10)
        
        if status_response.status_code == 200:
            status_data = status_response.json()
            
            statuses = status_data.get('statuses', {})
            ffm_status = statuses.get('ffm_status', 'unknown')
            backtest_status = statuses.get('backtest_status', 'unknown')
            
            print(f"  [{attempt:2d}/{max_attempts}] FFM: {ffm_status:10s} | Backtest: {backtest_status:10s}", end='')
            
            # Check if complete
            if ffm_status == 'complete' and backtest_status == 'complete':
                print(" ✅")
                print(f"\n✅ Analysis completed after ~{attempt * 3} seconds")
                break
            
            # Check for failures
            if ffm_status == 'failed' or backtest_status == 'failed':
                print(" ❌")
                error_msg = statuses.get('error_log', 'Unknown error')
                print(f"\n❌ Analysis failed: {error_msg}")
                exit(1)
            
            print()  # New line for next status
            
        elif status_response.status_code == 404:
            print(f"  [{attempt:2d}/{max_attempts}] Waiting for data to be uploaded...")
        else:
            print(f"  [{attempt:2d}/{max_attempts}] Unexpected status: {status_response.status_code}")
        
        # Wait before next poll
        if attempt < max_attempts:
            time.sleep(3)
            
    except requests.exceptions.RequestException as e:
        print(f"  [{attempt:2d}/{max_attempts}] Connection error: {e}")
        if attempt < max_attempts:
            time.sleep(3)
else:
    print(f"\n❌ Timeout: Analysis did not complete within {max_attempts * 3} seconds")
    print("   Check n8n execution logs and FastAPI logs for errors")
    exit(1)

# Step 3: Retrieve results
print(f"\n[3/3] Retrieving results...")

# Get FFM Results
try:
    ffm_url = f"{FASTAPI_URL}/api/v1/results/fama-french/{REQUEST_ID}"
    print(f"\nFetching FFM results from: {ffm_url}")
    ffm_response = requests.get(ffm_url, timeout=10)
    
    if ffm_response.status_code == 200:
        ffm_data = ffm_response.json()
        print("\n📊 Fama-French Model Results:")
        print("-" * 70)
        print(f"  Alpha:        {ffm_data.get('alpha', 'N/A'):.6f}")
        print(f"  Beta Market:  {ffm_data.get('beta_market', 'N/A'):.6f}")
        print(f"  Beta SMB:     {ffm_data.get('beta_smb', 'N/A'):.6f}")
        print(f"  Beta HML:     {ffm_data.get('beta_hml', 'N/A'):.6f}")
        print(f"  R-Squared:    {ffm_data.get('r_squared', 'N/A'):.6f}")
    else:
        print(f"⚠️  Could not fetch FFM results: {ffm_response.status_code}")
except Exception as e:
    print(f"⚠️  Error fetching FFM results: {e}")

# Get Backtest Results
try:
    backtest_url = f"{FASTAPI_URL}/api/v1/results/backtest/{REQUEST_ID}"
    print(f"\nFetching backtest results from: {backtest_url}")
    backtest_response = requests.get(backtest_url, timeout=10)
    
    if backtest_response.status_code == 200:
        bt_data = backtest_response.json()
        print("\n📈 Backtest Results:")
        print("-" * 70)
        print(f"  Sharpe Ratio:    {bt_data.get('sharpe_ratio', 'N/A'):.4f}")
        print(f"  Max Drawdown:    {bt_data.get('max_drawdown', 'N/A'):.2f}%")
        print(f"  Initial Value:   ${bt_data.get('initial_value', 'N/A'):,.2f}")
        print(f"  Final Value:     ${bt_data.get('final_value', 'N/A'):,.2f}")
        print(f"  Total Return:    {bt_data.get('total_return_pct', 'N/A'):.2f}%")
        
        params = bt_data.get('strategy_params', {})
        print(f"\n  Strategy Parameters:")
        print(f"    Fast MA: {params.get('fast_ma', 'N/A')}")
        print(f"    Slow MA: {params.get('slow_ma', 'N/A')}")
    else:
        print(f"⚠️  Could not fetch backtest results: {backtest_response.status_code}")
except Exception as e:
    print(f"⚠️  Error fetching backtest results: {e}")

print("\n" + "=" * 70)
print("✅ Complete! Results have been saved to Supabase.")
print("=" * 70)
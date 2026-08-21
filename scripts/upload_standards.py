"""上传参考标准文档并触发同步解析"""
import requests
import sys

BASE_URL = "http://localhost:8000"

# Step 1: 登录获取 token
print("=== Login ===")
login_resp = requests.post(
    f"{BASE_URL}/api/v1/auth/login",
    data={"username": "admin", "password": "123456"}
)
if login_resp.status_code != 200:
    print(f"[FAIL] Login failed: {login_resp.status_code} {login_resp.text}")
    sys.exit(1)

token = login_resp.json()["access_token"]
print("[OK] Login success")

headers = {"Authorization": f"Bearer {token}"}

# Step 2: 上传脂肪肝标准 (access_scope=operator)
print("\n=== Upload Fatty Liver Standard ===")
with open(r"C:\Users\86182\Desktop\脂肪肝标准.docx", "rb") as f:
    fl_resp = requests.post(
        f"{BASE_URL}/api/v1/admin/documents/upload",
        headers=headers,
        files={"file": ("脂肪肝标准.docx", f, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
        data={"access_scope": "operator"}
    )

if fl_resp.status_code != 200:
    print(f"[FAIL] Upload failed: {fl_resp.status_code} {fl_resp.text}")
    sys.exit(1)

fl_doc = fl_resp.json()
fl_doc_id = fl_doc["id"]
print(f"[OK] Uploaded: doc_id={fl_doc_id}, title={fl_doc.get('title')}")

# Trigger chunking
print(f"[INFO] Triggering chunking for doc_id={fl_doc_id}...")
chunk_resp = requests.post(f"{BASE_URL}/api/v1/admin/documents/{fl_doc_id}/chunk", headers=headers)
if chunk_resp.status_code != 200:
    print(f"[FAIL] Chunking failed: {chunk_resp.status_code} {chunk_resp.text}")
    sys.exit(1)
print(f"[OK] Chunking completed: {chunk_resp.json().get('chunk_count', 0)} chunks")

# Trigger indexing (vectorization)
print(f"[INFO] Triggering indexing for doc_id={fl_doc_id}...")
index_resp = requests.post(f"{BASE_URL}/api/v1/admin/documents/{fl_doc_id}/index", headers=headers)
if index_resp.status_code != 200:
    print(f"[FAIL] Indexing failed: {index_resp.status_code} {index_resp.text}")
    sys.exit(1)
print(f"[OK] Indexing completed")

# Step 3: 上传 AD 标准
print("\n=== Upload AD Standard ===")
with open(r"C:\Users\86182\Desktop\AD标准.docx", "rb") as f:
    ad_resp = requests.post(
        f"{BASE_URL}/api/v1/admin/documents/upload",
        headers=headers,
        files={"file": ("AD标准.docx", f, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
        data={"access_scope": "operator"}
    )

if ad_resp.status_code != 200:
    print(f"[FAIL] Upload failed: {ad_resp.status_code} {ad_resp.text}")
    sys.exit(1)

ad_doc = ad_resp.json()
ad_doc_id = ad_doc["id"]
print(f"[OK] Uploaded: doc_id={ad_doc_id}, title={ad_doc.get('title')}")

# Trigger chunking
print(f"[INFO] Triggering chunking for doc_id={ad_doc_id}...")
chunk_resp = requests.post(f"{BASE_URL}/api/v1/admin/documents/{ad_doc_id}/chunk", headers=headers)
if chunk_resp.status_code != 200:
    print(f"[FAIL] Chunking failed: {chunk_resp.status_code} {chunk_resp.text}")
    sys.exit(1)
print(f"[OK] Chunking completed: {chunk_resp.json().get('chunk_count', 0)} chunks")

# Trigger indexing (vectorization)
print(f"[INFO] Triggering indexing for doc_id={ad_doc_id}...")
index_resp = requests.post(f"{BASE_URL}/api/v1/admin/documents/{ad_doc_id}/index", headers=headers)
if index_resp.status_code != 200:
    print(f"[FAIL] Indexing failed: {index_resp.status_code} {index_resp.text}")
    sys.exit(1)
print(f"[OK] Indexing completed")

# Step 5: 触发参考范围同步（脂肪肝）
print("\n=== Sync Reference Ranges: Fatty Liver ===")
fl_sync_resp = requests.post(
    f"{BASE_URL}/api/v1/operator/reference-ranges/sync",
    headers=headers,
    json={"document_id": fl_doc_id}
)

if fl_sync_resp.status_code != 200:
    print(f"[FAIL] Sync failed: {fl_sync_resp.status_code} {fl_sync_resp.text}")
else:
    fl_sync_result = fl_sync_resp.json()
    print(f"[OK] Sync success: inserted={fl_sync_result.get('inserted')}, dropped={fl_sync_result.get('dropped')}")

# Step 6: 触发参考范围同步（AD）
print("\n=== Sync Reference Ranges: AD ===")
ad_sync_resp = requests.post(
    f"{BASE_URL}/api/v1/operator/reference-ranges/sync",
    headers=headers,
    json={"document_id": ad_doc_id}
)

if ad_sync_resp.status_code != 200:
    print(f"[FAIL] Sync failed: {ad_sync_resp.status_code} {ad_sync_resp.text}")
else:
    ad_sync_result = ad_sync_resp.json()
    print(f"[OK] Sync success: inserted={ad_sync_result.get('inserted')}, dropped={ad_sync_result.get('dropped')}")

print("\n=== Summary ===")
print(f"Fatty Liver doc_id: {fl_doc_id}")
print(f"AD doc_id: {ad_doc_id}")
print("Check database for extracted reference ranges.")

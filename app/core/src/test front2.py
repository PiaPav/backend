import base64
import binascii
import requests
from grpc_control.generated.api import core_pb2
from grpc_control.generated.shared import common_pb2

URL = "http://78.153.139.47:8080/core.api.FrontendStreamService/RunAlgorithm"

def encode_grpc_web_message(pb_msg):
    payload = pb_msg.SerializeToString()
    frame = b"\x00" + len(payload).to_bytes(4, "big") + payload
    return frame  # binary payload

def try_base64_decode_if_needed(buffer: bytes, content_type: str) -> (bytes, bool):
    if content_type and "grpc-web-text" in content_type:
        try:
            return base64.b64decode(buffer), True
        except Exception:
            return buffer, False
    try:
        buffer.decode('ascii')
        return base64.b64decode(buffer, validate=True), True
    except Exception:
        return buffer, False

def extract_frames_from_raw(raw: bytes):
    idx = 0
    frames = []
    total = len(raw)
    while idx + 5 <= total:
        flag = raw[idx]
        length = int.from_bytes(raw[idx+1:idx+5], "big")
        if idx + 5 + length > total:
            break
        payload = raw[idx+5:idx+5+length]
        frames.append((flag, payload))
        idx += 5 + length
    remainder = raw[idx:]
    return frames, remainder

def print_graph_part(msg: common_pb2.GraphPartResponse):
    print("\n----- GraphPartResponse -----")
    print(f"task_id: {msg.task_id}  response_id: {msg.response_id}  status: {common_pb2.ParseStatus.Name(msg.status)}")
    typ = msg.WhichOneof("graph_part_type")
    print("type:", typ)
    if typ == "graph_requirements":
        r = msg.graph_requirements
        print(" total:", r.total)
        print(" requirements:", list(r.requirements))
    elif typ == "graph_endpoints":
        e = msg.graph_endpoints
        print(" total:", e.total)
        print(" endpoints:", dict(e.endpoints))
    elif typ == "graph_architecture":
        a = msg.graph_architecture
        print(" parent:", a.parent)
        print(" children:", list(a.children))
    print("-----------------------------\n")

def grpc_web_stream_test(task_id: int):
    req = core_pb2.AlgorithmRequest(user_id=1, task_id=task_id)
    body = encode_grpc_web_message(req)

    headers = {
        "Content-Type": "application/grpc-web+proto",
        "X-Grpc-Web": "1",
        "Accept": "application/grpc-web+proto",
    }

    remainder = b""
    with requests.post(URL, headers=headers, data=body, stream=True) as resp:
        print("HTTP status:", resp.status_code)
        print("Response headers:", resp.headers)

        content_type = resp.headers.get("content-type", "")

        for chunk in resp.iter_content(chunk_size=8192):
            if not chunk:
                continue

            raw_candidate, was_base64 = try_base64_decode_if_needed(remainder + chunk, content_type)
            remainder = b""  # сбрасываем, так как уже декодировали
            frames, rem = extract_frames_from_raw(raw_candidate)
            remainder = rem

            for flag, payload in frames:
                if flag & 0x80:  # trailer frame
                    try:
                        print("Trailer frame:", payload.decode('ascii', errors='ignore'))
                    except Exception:
                        print("Trailer frame (binary):", binascii.hexlify(payload))
                    continue
                try:
                    msg = common_pb2.GraphPartResponse()
                    msg.ParseFromString(payload)
                    print_graph_part(msg)
                except Exception as e:
                    print("Protobuf parse error:", e)
                    print(" payload hex:", binascii.hexlify(payload[:80]))

        print("STREAM finished. HTTP headers (final):", resp.headers)

if __name__ == "__main__":
    grpc_web_stream_test(48)

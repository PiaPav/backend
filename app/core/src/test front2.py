import grpc
from grpc_control.generated.api import core_pb2, core_pb2_grpc
from grpc_control.generated.shared import common_pb2

MAX_RECEIVE = 50 * 1024 * 1024  # 50MB

def print_msg(msg):
    typ = msg.WhichOneof("graph_part_type")
    print(f"task_id={msg.task_id}, response_id={msg.response_id}, type={typ}")

def grpc_stream_all(task_id: int):
    options = [('grpc.max_receive_message_length', MAX_RECEIVE)]
    channel = grpc.insecure_channel("78.153.139.47:8080", options=options)
    stub = core_pb2_grpc.FrontendStreamServiceStub(channel)

    all_messages = []
    print(f"Начинаем сбор сообщений по task_id={task_id}...")

    try:
        req = core_pb2.AlgorithmRequest(user_id=1, task_id=task_id)
        responses = stub.RunAlgorithm(req)
        for msg in responses:
            all_messages.append(msg)
            print_msg(msg)

            if msg.status == common_pb2.ParseStatus.DONE:
                print("Получен DONE, поток завершён.")
                break

    except grpc.RpcError as e:
        print("gRPC ERROR:", e)

    print(f"Всего сообщений собрано: {len(all_messages)}")
    return all_messages

if __name__ == "__main__":
    msgs = grpc_stream_all(3)

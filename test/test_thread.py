def test_thread_1():
    import threading
    import time

    def work(stop_event: threading.Event) -> None:
        """工作线程执行的函数。"""
        try:
            # thread.start() 后，子线程开始执行这里的代码。
            print("Worker started")

            # 读取外层创建的线程对象的名称。
            print(thread.name)

            # 每次判断循环条件时，都会调用一次 wait()。
            #
            # wait(timeout=0.5)：
            # 让当前子线程等待停止信号，最多等待 0.5 秒。
            #
            # 情况一：等满 0.5 秒，没有收到信号。
            # wait() 返回 False。
            # not False 得到 True，进入循环体。
            #
            # 情况二：信号已经设置，或者等待期间收到信号。
            # wait() 返回 True，不必等满 0.5 秒。
            # not True 得到 False，退出循环。
            while not stop_event.wait(timeout=0.5):
                # 获取并打印当前正在执行这行代码的线程对象。
                # 每轮打印的都是同一个工作线程，不会创建新线程。
                print(threading.current_thread())

                # 模拟执行一次工作。
                print("Working")

                # 循环体执行完毕后，回到 while 条件，
                # 再次调用 wait()，开始下一轮等待。

        finally:
            # 正常退出循环或 try 中发生异常时，执行清理逻辑。
            # 实际使用时，可以在这里关闭文件、连接等资源。
            print("Worker cleanup")

        # work() 函数正常返回后，子线程结束。

    # 创建线程之间共享的信号对象。
    # 初始为“未设置”状态，此时 stop_event.is_set() 返回 False。
    # 在本程序中，约定“已设置”表示请求工作线程停止。
    stop_event = threading.Event()

    # 创建线程对象，此时 work() 尚未开始执行。
    thread = threading.Thread(
        target=work,  # 指定子线程执行的函数。
        args=(stop_event,),  # 将同一个 Event 对象传给 work()。
    )

    # 启动子线程，让它执行 work(stop_event)。
    # 主线程继续执行下面的代码。
    thread.start()

    # 只让主线程等待约 2 秒，子线程仍然可以运行。
    time.sleep(2)

    # 将 Event 的信号状态设为“已设置”。
    # 如果子线程正在 wait()，它可以提前结束等待并返回 True。
    # set() 只发出通知，子线程通过循环条件主动退出。
    stop_event.set()

    # 等待子线程执行完清理逻辑并真正结束。
    # join() 本身不会终止子线程。
    thread.join()

    # join() 返回后，可以确认子线程已经结束。
    print("Worker stopped")


def test_thread_2():
    import threading
    import time

    def worker(ready_event: threading.Event) -> None:
        print("Worker: waiting")

        ready_event.wait()  # 等待主线程发出通知

        print("Worker: continuing")

    ready_event = threading.Event()

    thread = threading.Thread(
        target=worker,
        args=(ready_event,),
    )
    thread.start()

    time.sleep(1)

    print("Main: sending signal")
    ready_event.set()

    thread.join()


def test_thread_3():
    import time
    import queue
    import threading

    jobs: queue.Queue[str | None] = queue.Queue()

    def worker() -> None:
        while True:
            item = jobs.get()
            print("Worker: waiting")
            time.sleep(2)

            try:
                # 使用 None 作为结束信号。
                if item is None:
                    return

                print(f"Processing: {item}")

            finally:
                jobs.task_done()

    thread = threading.Thread(target=worker)
    thread.start()

    jobs.put("Task A")
    jobs.put("Task B")
    jobs.put(None)

    # 等待所有放入队列的条目完成处理。
    jobs.join()

    # 等待工作线程真正结束。
    thread.join()

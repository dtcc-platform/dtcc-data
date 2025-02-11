import time
from fastapi import Request, status
from starlette.responses import Response

# We'll import these in the __main__ guard below to avoid issues
# from multiprocessing import Manager, Lock


def create_rate_limit_middleware(request_limit=100, time_window=60, global_request_limit=1000):
    """
    Returns a rate_limit_middleware function that uses multiprocessing.Manager() 
    structures to share data across multiple workers. The manager, dictionary, lists, 
    and lock are created once so all workers use the same objects.
    """
    from multiprocessing import Manager, Lock  # import here to avoid double-init in some setups

    manager = Manager()            # Manager server process
    lock = Lock()                  # A global lock to ensure atomic updates

    requests_count = manager.dict()  # { "client_ip": manager.list_of_timestamps }
    global_requests = manager.list() # list of timestamps for all requests

    # Initialize empty lists for new IPs on the fly
    # We'll do that inside the middleware logic.

    async def rate_limit_middleware(request: Request, call_next):
        now = time.time()
        client_ip = request.client.host

        with lock:
            # ------------------------
            # 1) Prune old timestamps in global list
            # ------------------------
            valid_global = [t for t in global_requests if t > now - time_window]
            # Replace the entire list in place
            global_requests[:] = valid_global

            # ------------------------
            # 2) Check global limit
            # ------------------------
            if len(global_requests) >= global_request_limit:
                return Response(
                    content="Global request limit reached. Please wait.",
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS
                )

            # ------------------------
            # 3) Per-IP cleanup
            # ------------------------
            if client_ip not in requests_count:
                # each new IP gets its own manager.list
                requests_count[client_ip] = manager.list()

            valid_times = [t for t in requests_count[client_ip] if t > now - time_window]
            # Replace the entire per-IP list
            requests_count[client_ip][:] = valid_times

            # ------------------------
            # 4) Check per-IP limit
            # ------------------------
            if len(requests_count[client_ip]) >= request_limit:
                return Response(
                    content="Too many requests from this IP. Please slow down.",
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS
                )

            # ------------------------
            # 5) Record the new request
            # ------------------------
            requests_count[client_ip].append(now)
            global_requests.append(now)

        # If we get here, pass the request down to the endpoint
        response = await call_next(request)
        return response

    return rate_limit_middleware

"""Python diagnostic guard for the offline demo, not an OS sandbox."""
import os
import sys


def install():
    os.environ.update(MLFLOW_ENABLE_ASYNC_LOGGING='false', MLFLOW_ENABLE_SYSTEM_METRICS_LOGGING='false',
                      DO_NOT_TRACK='1', HF_HUB_OFFLINE='1', OMP_NUM_THREADS='2',
                      OPENBLAS_NUM_THREADS='2', MKL_NUM_THREADS='2')
    def audit(event, args):
        if event in ('socket.connect','socket.connect_ex','socket.sendto','socket.getaddrinfo',
                     'socket.gethostbyname','socket.gethostbyname_ex'):
            raise PermissionError('PRISM_PUBLIC_EXTERNAL_NETWORK_REFUSED')
    sys.addaudithook(audit)

"""Allocation admission bounded by working memory, never by four strategies."""
import ctypes
import math
from .event_clock import require

def resource_budget():
    ceiling=256*1024*1024
    available=None
    try:
        class Memory(ctypes.Structure):
            _fields_=[('length',ctypes.c_ulong),('load',ctypes.c_ulong),
                      *[(n,ctypes.c_ulonglong) for n in ('physical','available','pagefile','available_pagefile','virtual','available_virtual','extended')]]
        info=Memory();info.length=ctypes.sizeof(info)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(info)):
            available=int(info.available)
    except (AttributeError,OSError):pass
    budget=min(ceiling,available//8) if available else 64*1024*1024
    return {'budget_bytes':budget,'available_physical_bytes':available,
            'policy':'min(256MiB, available physical memory / 8); conservative 64MiB fallback'}

def validate_capacity(rows,strategies,*,budget_bytes=None,decoded_bytes=0):
    require(type(rows) is int and type(strategies) is int and rows>=0 and strategies>=1,
            'INVALID_PORTFOLIO_DIMENSIONS')
    budget=resource_budget()['budget_bytes'] if budget_bytes is None else budget_bytes
    require(type(budget) is int and budget>0,'INVALID_RESOURCE_BUDGET')
    # Numeric pivot copies, masks, covariance/correlation/solver work arrays.
    estimate=rows*8*8+strategies*strategies*8*12+max(0,int(decoded_bytes))*4
    require(estimate<=budget,'PORTFOLIO_MEMORY_BUDGET_EXCEEDED')
    return {'rows':rows,'strategies':strategies,'estimated_working_bytes':estimate,'budget_bytes':budget,
            'strategy_count_policy':'No fixed strategy cap; row/byte and quadratic matrix resource admission'}

def validate_position_limit(count):
    require(type(count) is int and count>=1,'INVALID_MAX_POSITIONS')
    validate_capacity(0,count)

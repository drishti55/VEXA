def primes_below(n):
    out = []
    for k in range(2, n):
        if all(k % d for d in range(2, k)):
            out.append(k)
    return out

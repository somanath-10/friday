from friday.tools.cache import cached_tool, clear_cache

def test_cached_tool():
    clear_cache()

    execution_count = 0

    @cached_tool(ttl_seconds=10)
    def dummy_expensive_function(x, y):
        nonlocal execution_count
        execution_count += 1
        return x + y

    # First call, should execute
    res1 = dummy_expensive_function(1, 2)
    assert res1 == 3
    assert execution_count == 1

    # Second call, exact same arguments, should HIT cache
    res2 = dummy_expensive_function(1, 2)
    assert res2 == 3
    assert execution_count == 1  # Execution count did not increase!

    # Third call, different arguments, should MISS cache
    res3 = dummy_expensive_function(2, 3)
    assert res3 == 5
    assert execution_count == 2

    clear_cache()

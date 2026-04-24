import asyncio

from friday.tools.error_handling import validate_inputs


def test_validate_inputs_blocks_oversized_sync_args():
    @validate_inputs(max_str_len=5)
    def echo(text: str) -> str:
        return text

    assert echo("123456") == (
        "[Security Block] Argument 0 exceeded maximum allowed length of 5 characters."
    )


def test_validate_inputs_blocks_oversized_async_kwargs():
    @validate_inputs(max_str_len=5)
    async def echo(*, text: str) -> str:
        return text

    result = asyncio.run(echo(text="123456"))
    assert result == (
        "[Security Block] Input 'text' exceeded maximum allowed length of 5 characters."
    )


def test_validate_inputs_allows_safe_async_inputs():
    @validate_inputs(max_str_len=5)
    async def echo(text: str) -> str:
        return text

    assert asyncio.run(echo("12345")) == "12345"

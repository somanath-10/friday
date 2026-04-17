"""
Finance tools — real-time stocks, crypto prices, and currency conversion.
All free APIs, no key required.
"""
import httpx
import re


async def _fetch(client: httpx.AsyncClient, url: str, **kwargs) -> dict | None:
    try:
        r = await client.get(url, timeout=10, **kwargs)
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return None


def register(mcp):

    @mcp.tool()
    async def get_stock_price(symbol: str) -> str:
        """
        Get the current real-time stock price for any publicly traded company.
        symbol: Stock ticker symbol (e.g. 'AAPL', 'TSLA', 'GOOGL', 'RELIANCE.NS', 'TCS.NS').
        Use '.NS' suffix for Indian NSE stocks (e.g. 'INFY.NS').
        Use this when the user asks about stock prices, market cap, PE ratio, etc.
        """
        symbol = symbol.upper().strip()
        try:
            async with httpx.AsyncClient(follow_redirects=True) as client:
                # Yahoo Finance v8 API (free, no key)
                url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range=1d"
                headers = {"User-Agent": "Mozilla/5.0"}
                r = await client.get(url, headers=headers, timeout=10)
                if r.status_code != 200:
                    return f"Could not find stock symbol '{symbol}'. Try the full ticker (e.g. 'AAPL', 'TCS.NS')."
                data = r.json()
                meta = data["chart"]["result"][0]["meta"]
                price = meta.get("regularMarketPrice", "N/A")
                prev_close = meta.get("chartPreviousClose", meta.get("previousClose", "N/A"))
                currency = meta.get("currency", "USD")
                exchange = meta.get("exchangeName", "")
                name = meta.get("longName", symbol)
                high = meta.get("regularMarketDayHigh", "N/A")
                low = meta.get("regularMarketDayLow", "N/A")
                volume = meta.get("regularMarketVolume", "N/A")

                if isinstance(price, float) and isinstance(prev_close, float):
                    change = price - prev_close
                    change_pct = (change / prev_close) * 100
                    direction = "+" if change >= 0 else ""
                    change_str = f"{direction}{change:.2f} ({direction}{change_pct:.2f}%)"
                else:
                    change_str = "N/A"

                return (
                    f"=== {name} ({symbol}) ===\n"
                    f"Price     : {currency} {price}\n"
                    f"Change    : {change_str}\n"
                    f"Day H/L   : {high} / {low}\n"
                    f"Prev Close: {prev_close}\n"
                    f"Volume    : {volume:,}" if isinstance(volume, int) else f"Volume    : {volume}\n"
                    f"Exchange  : {exchange}"
                )
        except Exception as e:
            return f"Error fetching stock price for '{symbol}': {str(e)}"

    @mcp.tool()
    async def get_crypto_price(coin: str) -> str:
        """
        Get the current price and 24h stats for any cryptocurrency.
        coin: Coin name or ID (e.g. 'bitcoin', 'ethereum', 'solana', 'dogecoin', 'bnb').
        Use this when the user asks about crypto prices, Bitcoin, Ethereum, etc.
        """
        coin_id = coin.lower().strip().replace(" ", "-")
        # Ticker symbol map for Yahoo Finance fallback
        yahoo_map = {
            "bitcoin": "BTC-USD", "ethereum": "ETH-USD", "solana": "SOL-USD",
            "dogecoin": "DOGE-USD", "bnb": "BNB-USD", "cardano": "ADA-USD",
            "ripple": "XRP-USD", "xrp": "XRP-USD", "litecoin": "LTC-USD",
            "polkadot": "DOT-USD", "chainlink": "LINK-USD", "avax": "AVAX-USD",
            "avalanche": "AVAX-USD", "shiba-inu": "SHIB-USD",
        }
        headers = {"User-Agent": "Mozilla/5.0"}
        try:
            async with httpx.AsyncClient(follow_redirects=True, timeout=12) as client:

                # --- Priority 1: CoinGecko ---
                try:
                    r = await client.get(
                        "https://api.coingecko.com/api/v3/coins/markets",
                        params={"vs_currency": "usd", "ids": coin_id,
                                "order": "market_cap_desc", "per_page": 1, "page": 1},
                        timeout=8,
                    )
                    if r.status_code == 200:
                        data = r.json()
                        if data:
                            c = data[0]
                            price = c.get("current_price", "N/A")
                            change_24h = c.get("price_change_percentage_24h", 0) or 0
                            high_24h = c.get("high_24h", "N/A")
                            low_24h = c.get("low_24h", "N/A")
                            market_cap = c.get("market_cap", "N/A")
                            rank = c.get("market_cap_rank", "N/A")
                            sym = c.get("symbol", "").upper()
                            name = c.get("name", coin.capitalize())
                            direction = "+" if change_24h >= 0 else ""
                            return (
                                f"=== {name} ({sym}) — via CoinGecko ===\n"
                                f"Price     : ${price:,.4f}\n"
                                f"24h Change: {direction}{change_24h:.2f}%\n"
                                f"24h H/L   : ${high_24h:,.4f} / ${low_24h:,.4f}\n"
                                f"Market Cap: ${market_cap:,.0f}\n"
                                f"CMC Rank  : #{rank}"
                            )
                except Exception:
                    pass  # Fall through to next source

                # --- Priority 2: Coinpaprika (free, no key, generous limits) ---
                try:
                    r = await client.get(
                        f"https://api.coinpaprika.com/v1/tickers/{coin_id}",
                        timeout=8,
                    )
                    if r.status_code == 200:
                        d = r.json()
                        q = d.get("quotes", {}).get("USD", {})
                        price = q.get("price", "N/A")
                        change_24h = q.get("percent_change_24h", 0) or 0
                        market_cap = q.get("market_cap", "N/A")
                        rank = d.get("rank", "N/A")
                        sym = d.get("symbol", "").upper()
                        name = d.get("name", coin.capitalize())
                        direction = "+" if change_24h >= 0 else ""
                        return (
                            f"=== {name} ({sym}) — via Coinpaprika ===\n"
                            f"Price     : ${price:,.4f}\n"
                            f"24h Change: {direction}{change_24h:.2f}%\n"
                            f"Market Cap: ${market_cap:,.0f}\n"
                            f"Rank      : #{rank}"
                        )
                    elif r.status_code == 404:
                        pass  # coin not found, try Yahoo
                except Exception:
                    pass

                # --- Priority 3: Yahoo Finance (ticker symbol) ---
                yahoo_sym = yahoo_map.get(coin_id, f"{coin_id.upper().split('-')[0]}-USD")
                try:
                    r = await client.get(
                        f"https://query1.finance.yahoo.com/v8/finance/chart/{yahoo_sym}?interval=1d&range=1d",
                        headers=headers, timeout=8,
                    )
                    if r.status_code == 200:
                        meta = r.json()["chart"]["result"][0]["meta"]
                        price = meta.get("regularMarketPrice", "N/A")
                        prev = meta.get("chartPreviousClose", meta.get("previousClose"))
                        if isinstance(price, float) and prev:
                            chg = price - prev
                            pct = (chg / prev) * 100
                            d = "+" if chg >= 0 else ""
                            return (
                                f"=== {coin.upper()} ({yahoo_sym}) — via Yahoo Finance ===\n"
                                f"Price     : ${price:,.4f}\n"
                                f"24h Change: {d}{pct:.2f}%\n"
                                f"Prev Close: ${prev:,.4f}"
                            )
                except Exception:
                    pass

            return (
                f"Could not retrieve price for '{coin}'. "
                "All sources (CoinGecko, Coinpaprika, Yahoo) are unavailable. Try again shortly."
            )
        except Exception as e:
            return f"Error fetching crypto price for '{coin}': {str(e)}"


    @mcp.tool()
    async def convert_currency(amount: float, from_currency: str, to_currency: str) -> str:
        """
        Convert an amount between any two currencies using live exchange rates.
        from_currency: Source currency code (e.g. 'USD', 'INR', 'EUR', 'GBP').
        to_currency: Target currency code.
        Use this when the user asks 'how much is X USD in INR?', 'convert dollars to euros', etc.
        """
        from_c = from_currency.upper().strip()
        to_c = to_currency.upper().strip()
        try:
            async with httpx.AsyncClient(follow_redirects=True) as client:
                # ExchangeRate-API free endpoint
                url = f"https://api.exchangerate-api.com/v4/latest/{from_c}"
                r = await client.get(url, timeout=10)
                if r.status_code != 200:
                    return f"Could not fetch exchange rate for '{from_c}'. Check the currency code."
                data = r.json()
                rates = data.get("rates", {})
                if to_c not in rates:
                    return f"Currency '{to_c}' not found. Use standard ISO codes like USD, EUR, INR, GBP."
                rate = rates[to_c]
                result = amount * rate
                return (
                    f"Currency Conversion:\n"
                    f"  {amount:,.2f} {from_c} = {result:,.2f} {to_c}\n"
                    f"  Exchange Rate: 1 {from_c} = {rate:.4f} {to_c}"
                )
        except Exception as e:
            return f"Error converting currency: {str(e)}"

    @mcp.tool()
    async def get_market_summary() -> str:
        """
        Get a quick summary of major global market indices (S&P 500, NASDAQ, Dow Jones, Nifty 50).
        Use this when the user asks 'how are markets doing?', 'market overview', etc.
        """
        indices = {
            "S&P 500": "^GSPC",
            "NASDAQ": "^IXIC",
            "Dow Jones": "^DJI",
            "Nifty 50": "^NSEI",
            "Sensex": "^BSESN",
        }
        headers = {"User-Agent": "Mozilla/5.0"}
        results = []
        async with httpx.AsyncClient(follow_redirects=True) as client:
            for name, sym in indices.items():
                try:
                    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?interval=1d&range=1d"
                    r = await client.get(url, headers=headers, timeout=8)
                    if r.status_code == 200:
                        meta = r.json()["chart"]["result"][0]["meta"]
                        price = meta.get("regularMarketPrice", "N/A")
                        prev = meta.get("chartPreviousClose", meta.get("previousClose"))
                        if isinstance(price, float) and prev:
                            chg = price - prev
                            pct = (chg / prev) * 100
                            d = "+" if chg >= 0 else ""
                            results.append(f"  {name:<12}: {price:>10,.2f}  {d}{pct:.2f}%")
                        else:
                            results.append(f"  {name:<12}: {price}")
                except Exception:
                    results.append(f"  {name:<12}: unavailable")
        if not results:
            return "Unable to fetch market data at this time."
        return "=== GLOBAL MARKET SUMMARY ===\n" + "\n".join(results)

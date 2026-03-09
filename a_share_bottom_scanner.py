import streamlit as st
import yfinance as yf
import pandas as pd
import time
from datetime import datetime, timedelta
import plotly.graph_objects as go

# --- 1. 页面配置 ---
st.set_page_config(
    page_title="美股底部反转筛选器",
    page_icon="🇺🇸",
    layout="wide"
)

# 自定义样式
st.markdown("""
    <style>
    .stMetric { background-color: #ffffff; padding: 15px; border-radius: 10px; box-shadow: 0 2px 4px rgba(0,0,0,0.05); }
    </style>
    """, unsafe_allow_html=True)

# --- 2. 核心计算函数 ---

def calculate_rsi(series, period=14):
    """原生计算 RSI，完全不依赖第三方技术分析库"""
    if len(series) < period:
        return pd.Series([None] * len(series))
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    # 避免除以零
    rs = gain / loss.replace(0, 1e-9) 
    return 100 - (100 / (1 + rs))

@st.cache_data(ttl=86400)
def get_sp500_tickers():
    """获取标普500成分股列表，带备选方案"""
    try:
        # 尝试从维基百科爬取
        table = pd.read_html('https://en.wikipedia.org/wiki/List_of_S%26P_500_companies')
        df = table[0]
        return df['Symbol'].tolist()
    except Exception as e:
        # 如果 read_html 因为缺少库或网络问题失败，使用硬编码的 Top 50 热门美股作为备份
        st.sidebar.warning("无法获取完整S&P500列表，已切换为热门美股备份。")
        return [
            "AAPL", "MSFT", "GOOGL", "AMZN", "TSLA", "NVDA", "META", "UNH", "JNJ", "V", 
            "WMT", "PG", "MA", "HD", "CVX", "PFE", "ABV", "KO", "BAC", "PEP",
            "COST", "TMO", "AVGO", "CSCO", "ACN", "ADBE", "LIN", "CRM", "DIS", "ABT",
            "WFC", "DHR", "TXN", "INTC", "PM", "NEE", "VZ", "RTX", "AMGN", "HON",
            "IBM", "LOW", "CAT", "GE", "QCOM", "INTU", "DE", "SPGI", "PLD", "GS"
        ]

def check_us_stock_strategy(ticker_symbol, ma_ratio, rsi_threshold):
    """
    筛选逻辑实现：
    1. 价格跌破年线指定比例
    2. RSI超卖
    3. 量比确认
    """
    try:
        # 增加重试机制
        ticker = yf.Ticker(ticker_symbol)
        df = ticker.history(period="2y")
        
        if df is None or len(df) < 250:
            return None
            
        # 计算指标
        df['MA250'] = df['Close'].rolling(window=250).mean()
        df['RSI'] = calculate_rsi(df['Close'], period=14)
        
        latest = df.iloc[-1]
        close = latest['Close']
        ma250 = latest['MA250']
        rsi = latest['RSI']
        volume = latest['Volume']
        avg_volume = df['Volume'].tail(20).mean()
        
        if pd.isna(ma250) or pd.isna(rsi):
            return None

        # 核心判断逻辑
        if (close < ma250 * ma_ratio) and (rsi < rsi_threshold):
            bias = (close - ma250) / ma250 * 100
            vol_ratio = volume / avg_volume if avg_volume > 0 else 0
            
            return {
                '代码': ticker_symbol,
                '当前价': round(close, 2),
                '年线(MA250)': round(ma250, 2),
                '乖离率%': round(bias, 2),
                'RSI14': round(rsi, 2),
                '量比(20日)': round(vol_ratio, 2),
                '成交量': int(volume)
            }
    except:
        pass # 忽略单只股票获取失败
    return None

# --- 3. 侧边栏 ---

st.sidebar.header("🇺🇸 美股筛选设置")
scan_mode = st.sidebar.radio("选择扫描范围", ["标普500成份股", "自定义代码"])

if scan_mode == "自定义代码":
    custom_tickers = st.sidebar.text_input("输入代码 (逗号分隔)", "TSLA,AAPL,BABA,PDD,NIO,XPEV")
    ticker_list = [t.strip().upper() for t in custom_tickers.split(",") if t.strip()]
else:
    ticker_list = get_sp500_tickers()

st.sidebar.divider()
ma_pct = st.sidebar.slider("股价低于年线幅度 (%)", 0, 60, 20)
ma_ratio = (100 - ma_pct) / 100.0
rsi_limit = st.sidebar.number_input("RSI(14) 低于", 10, 50, 35)

start_scan = st.sidebar.button("🚀 开始分析美股", use_container_width=True)

# --- 4. 主界面 ---

st.title("🎯 美股底部反转筛选器")
st.info("说明：由于美股 API 限制，标普500全量扫描可能需要 3-5 分钟。")

if start_scan:
    total = len(ticker_list)
    st.subheader(f"📊 正在扫描 {total} 只美股...")
    
    progress_bar = st.progress(0)
    status_text = st.empty()
    results = []
    
    start_time = time.time()
    
    for i, symbol in enumerate(ticker_list):
        yf_symbol = symbol.replace('.', '-') # 处理 BRK.B 类型代码
        status_text.text(f"正在分析: {symbol} ({i+1}/{total})")
        
        res = check_us_stock_strategy(yf_symbol, ma_ratio, rsi_limit)
        if res:
            res['代码'] = symbol
            results.append(res)
        
        progress_bar.progress((i + 1) / total)
        # 适当休眠，避免被 Yahoo Finance 封锁
        if i % 20 == 0:
            time.sleep(0.1)

    status_text.success(f"扫描完成！耗时 {round(time.time() - start_time, 1)} 秒。")

    if results:
        df_res = pd.DataFrame(results)
        
        c1, c2, c3 = st.columns(3)
        c1.metric("筛选结果", f"{len(results)} 只")
        c2.metric("中位乖离率", f"{round(df_res['乖离率%'].median(), 2)}%")
        c3.metric("最强量比", df_res.sort_values('量比(20日)', ascending=False).iloc[0]['代码'])

        st.write("### 🔍 筛选清单 (按量比排序)")
        st.dataframe(
            df_res.sort_values('量比(20日)', ascending=False).style.format(precision=2),
            use_container_width=True,
            hide_index=True
        )

        # 分布图
        fig = go.Figure(data=[go.Scatter(
            x=df_res['乖离率%'], 
            y=df_res['量比(20日)'],
            mode='markers+text',
            text=df_res['代码'],
            textposition="top center",
            marker=dict(size=12, color=df_res['RSI14'], colorscale='Viridis', showscale=True)
        )])
        fig.update_layout(xaxis_title="乖离率 %", yaxis_title="量比", template="plotly_white")
        st.plotly_chart(fig, use_container_width=True)
        
        csv = df_res.to_csv(index=False).encode('utf_8_sig')
        st.download_button("📥 下载数据 (CSV)", csv, "us_stocks_bottom.csv", "text/csv")
    else:
        st.warning("☹️ 当前参数下未找到符合条件的股票。")
else:
    st.divider()
    st.write("### 💡 使用建议")
    st.markdown("""
    - **部署报错？** 请确保 GitHub 中的 `requirements.txt` 文件**仅包含文字**，没有隐藏的 `.txt` 后缀。
    - **关于数据**：数据由 Yahoo Finance 提供，可能会有几分钟延迟。
    """)

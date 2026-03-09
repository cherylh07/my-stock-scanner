import streamlit as st
import yfinance as yf
import pandas as pd
import pandas_ta as ta
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

# --- 2. 数据获取逻辑 ---

@st.cache_data(ttl=86400)
def get_sp500_tickers():
    """获取标普500成分股列表 (从维基百科)"""
    try:
        table = pd.read_html('https://en.wikipedia.org/wiki/List_of_S%26P_500_companies')
        df = table[0]
        return df['Symbol'].tolist()
    except:
        return ["AAPL", "MSFT", "GOOGL", "AMZN", "TSLA", "NVDA", "META", "UNH", "JNJ", "V"]

def check_us_stock_strategy(ticker_symbol, ma_ratio, rsi_threshold):
    """
    美股筛选逻辑：
    1. 价格 < 250日均线 (年线) 的指定比例
    2. RSI(14) < 阈值 (超卖)
    3. 近期成交量异动 (作为资金进场参考)
    """
    try:
        # 获取最近两年的数据以确保计算 MA250
        ticker = yf.Ticker(ticker_symbol)
        df = ticker.history(period="2y")
        
        if len(df) < 250:
            return None
            
        # 计算指标
        df['MA250'] = ta.sma(df['Close'], length=250)
        df['RSI'] = ta.rsi(df['Close'], length=14)
        
        latest = df.iloc[-1]
        prev = df.iloc[-2]
        
        close = latest['Close']
        ma250 = latest['MA250']
        rsi = latest['RSI']
        volume = latest['Volume']
        avg_volume = df['Volume'].tail(20).mean() # 20日平均成交额
        
        # 筛选条件：价格在年线下方的超跌区间 + RSI超卖
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
        return None
    except:
        return None

# --- 3. 侧边栏 ---

st.sidebar.header("🇺🇸 美股筛选设置")

scan_mode = st.sidebar.radio("选择扫描模式", ["标普500成份股", "自定义代码"])

if scan_mode == "自定义代码":
    custom_tickers = st.sidebar.text_input("输入美股代码 (用逗号分隔)", "TSLA,AAPL,BABA,PPD,PDD,NIO")
    ticker_list = [t.strip().upper() for t in custom_tickers.split(",")]
else:
    ticker_list = get_sp500_tickers()

st.sidebar.divider()
ma_pct = st.sidebar.slider("股价低于年线幅度 (%)", 0, 60, 20)
ma_ratio = (100 - ma_pct) / 100.0
rsi_limit = st.sidebar.number_input("RSI(14) 低于", 10, 50, 35)

start_scan = st.sidebar.button("🚀 开始分析美股", use_container_width=True)

# --- 4. 主界面 ---

st.title("🎯 美股底部反转筛选器")
st.info("原理：在美股市场寻找处于**250日年线**下方、**RSI超卖**且具备成交量支撑的潜在反转标的。")

if start_scan:
    total = len(ticker_list)
    st.subheader(f"📊 正在分析 {total} 只美股标的...")
    
    progress_bar = st.progress(0)
    status_text = st.empty()
    results = []
    
    start_time = time.time()
    
    # 开始遍历
    for i, symbol in enumerate(ticker_list):
        status_text.text(f"正在扫描: {symbol} ({i+1}/{total})")
        res = check_us_stock_strategy(symbol, ma_ratio, rsi_limit)
        if res:
            results.append(res)
        
        progress_bar.progress((i + 1) / total)
        # yfinance 限制较少，但建议不要过快
        if i % 10 == 0:
            time.sleep(0.1)

    duration = round(time.time() - start_time, 1)
    status_text.success(f"扫描完成！耗时 {duration} 秒。")

    if results:
        df_res = pd.DataFrame(results)
        
        # 数据卡片
        c1, c2, c3 = st.columns(3)
        c1.metric("符合条件数", len(results))
        c2.metric("平均超跌幅度", f"{round(df_res['乖离率%'].mean(), 2)}%")
        with c3:
            max_vol = df_res.sort_values('量比(20日)', ascending=False).iloc[0]['代码']
            st.metric("相对放量之王", max_vol)

        st.write("### 🔍 美股筛选结果清单")
        # 排序：按量比降序排列
        df_res = df_res.sort_values('量比(20日)', ascending=False)
        
        st.dataframe(
            df_res.style.background_gradient(subset=['量比(20日)'], cmap='YlGn')
                       .background_gradient(subset=['乖离率%'], cmap='RdYlGn_r'),
            use_container_width=True,
            hide_index=True
        )

        # 散点图分析
        st.write("### 📈 乖离率与量比分布图")
        fig = go.Figure(data=[go.Scatter(
            x=df_res['乖离率%'], 
            y=df_res['量比(20日)'],
            mode='markers+text',
            text=df_res['代码'],
            textposition="top center",
            marker=dict(size=df_res['RSI14'], color=df_res['RSI14'], colorscale='Viridis', showscale=True)
        )])
        fig.update_layout(
            xaxis_title="乖离率 % (越小越跌过头)",
            yaxis_title="量比 (相对于20日平均)",
            template="plotly_white"
        )
        st.plotly_chart(fig, use_container_width=True)
        
        # 下载
        csv = df_res.to_csv(index=False).encode('utf_8_sig')
        st.download_button("📥 下载结果 (CSV)", csv, "us_bottom_scan.csv", "text/csv")
        
    else:
        st.warning("☹️ 未找到符合条件的美股。可以尝试放宽筛选参数（例如增加 RSI 阈值或减少超跌比例）。")
else:
    st.divider()
    st.write("### 💡 使用小贴士")
    st.markdown("""
    - **美股代码**：例如苹果输入 `AAPL`，特斯拉输入 `TSLA`。
    - **乖离率**：美股如果跌破年线 20%-30% 通常代表极度超跌。
    - **量比**：量比大于 1 代表今日成交活跃度超过近一个月平均水平，可能是资金入场的信号。
    """)
  

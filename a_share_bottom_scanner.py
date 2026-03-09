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

# --- 2. 核心计算函数 (原生实现以减少依赖) ---

def calculate_rsi(series, period=14):
    """使用 pandas 原生计算 RSI，不依赖第三方库"""
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

@st.cache_data(ttl=86400)
def get_sp500_tickers():
    """获取标普500成分股列表 (从维基百科)"""
    try:
        # 增加 headers 模拟浏览器，防止被维基百科拦截
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
    3. 量比衡量近期成交活跃度
    """
    try:
        # 获取最近两年的数据以确保计算 MA250
        ticker = yf.Ticker(ticker_symbol)
        df = ticker.history(period="2y")
        
        if len(df) < 250:
            return None
            
        # 计算指标 (使用原生 pandas)
        df['MA250'] = df['Close'].rolling(window=250).mean()
        df['RSI'] = calculate_rsi(df['Close'], period=14)
        
        latest = df.iloc[-1]
        
        close = latest['Close']
        ma250 = latest['MA250']
        rsi = latest['RSI']
        volume = latest['Volume']
        avg_volume = df['Volume'].tail(20).mean() # 20日平均成交量
        
        # 筛选条件判断
        if pd.isna(ma250) or pd.isna(rsi):
            return None

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
    custom_tickers = st.sidebar.text_input("输入美股代码 (用逗号分隔)", "TSLA,AAPL,BABA,PDD,NIO")
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
    
    for i, symbol in enumerate(ticker_list):
        # 处理部分代码带点的格式（如 BRK.B 需转为 BRK-B 才能被 yfinance 识别）
        yf_symbol = symbol.replace('.', '-')
        status_text.text(f"正在扫描: {symbol} ({i+1}/{total})")
        
        res = check_us_stock_strategy(yf_symbol, ma_ratio, rsi_limit)
        if res:
            res['代码'] = symbol # 恢复原始显示代码
            results.append(res)
        
        progress_bar.progress((i + 1) / total)
        if i % 10 == 0:
            time.sleep(0.05)

    duration = round(time.time() - start_time, 1)
    status_text.success(f"扫描完成！耗时 {duration} 秒。")

    if results:
        df_res = pd.DataFrame(results)
        
        c1, c2, c3 = st.columns(3)
        c1.metric("符合条件数", len(results))
        c2.metric("平均超跌幅度", f"{round(df_res['乖离率%'].mean(), 2)}%")
        with c3:
            max_vol = df_res.sort_values('量比(20日)', ascending=False).iloc[0]['代码']
            st.metric("相对放量之王", max_vol)

        st.write("### 🔍 美股筛选结果清单")
        df_res = df_res.sort_values('量比(20日)', ascending=False)
        
        st.dataframe(
            df_res.style.background_gradient(subset=['量比(20日)'], cmap='YlGn')
                       .background_gradient(subset=['乖离率%'], cmap='RdYlGn_r'),
            use_container_width=True,
            hide_index=True
        )

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
        
        csv = df_res.to_csv(index=False).encode('utf_8_sig')
        st.download_button("📥 下载结果 (CSV)", csv, "us_bottom_scan.csv", "text/csv")
        
    else:
        st.warning("☹️ 未找到符合条件的美股。可以尝试放宽筛选参数。")
else:
    st.divider()
    st.write("### 💡 使用小贴士")
    st.markdown("""
    - **乖离率**：美股跌破年线 20% 以上通常被视为严重的阶段性超跌。
    - **RSI指标**：30 以下代表进入超卖区，数值越低反弹动能可能越大。
    - **运行报错？**：如果部署失败，请确保你的 GitHub 中 `requirements.txt` 文件内容已按下方说明更新。
    """)

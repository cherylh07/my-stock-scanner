import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import time
from datetime import datetime
import plotly.graph_objects as go

# --- 1. 页面配置 ---
st.set_page_config(
    page_title="美股底部共振筛选器",
    page_icon="🇺🇸",
    layout="wide"
)

# 自定义 CSS 样式
st.markdown("""
    <style>
    .stMetric { background-color: #ffffff; padding: 15px; border-radius: 10px; box-shadow: 0 2px 4px rgba(0,0,0,0.05); }
    .status-box { padding: 10px; border-radius: 5px; margin-bottom: 10px; }
    </style>
    """, unsafe_allow_html=True)

# --- 2. 核心计算函数 ---

def calculate_rsi(series, period=14):
    """原生计算 RSI"""
    if len(series) < period: return pd.Series([np.nan] * len(series))
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss.replace(0, 1e-9)
    return 100 - (100 / (1 + rs))

def calculate_mfi(df, period=14):
    """
    计算资金流量指数 (Money Flow Index)
    MFI > 50 且在上升通常意味着资金流入
    """
    typical_price = (df['High'] + df['Low'] + df['Close']) / 3
    money_flow = typical_price * df['Volume']
    
    delta = typical_price.diff()
    pos_flow = pd.Series(np.where(delta > 0, money_flow, 0), index=df.index).rolling(window=period).sum()
    neg_flow = pd.Series(np.where(delta < 0, money_flow, 0), index=df.index).rolling(window=period).sum()
    
    mfr = pos_flow / neg_flow.replace(0, 1e-9)
    return 100 - (100 / (1 + mfr))

@st.cache_data(ttl=86400)
def get_sp500_data():
    """实时获取标普500成分股及其行业分类"""
    try:
        url = 'https://en.wikipedia.org/wiki/List_of_S%26P_500_companies'
        tables = pd.read_html(url)
        df = tables[0]
        # 返回代码和行业的字典映射
        return df[['Symbol', 'GICS Sector']]
    except Exception as e:
        st.error(f"无法获取行业数据: {e}")
        return pd.DataFrame(columns=['Symbol', 'GICS Sector'])

def get_inst_holdings(ticker_symbol):
    """获取机构持仓比例 (用于最终确认)"""
    try:
        t = yf.Ticker(ticker_symbol)
        info = t.info
        # 机构持仓百分比
        hold = info.get('heldPercentInstitutions', 0)
        return round(hold * 100, 2) if hold else 0
    except:
        return 0

def check_stock_strategy(symbol, ma_ratio_threshold, rsi_threshold):
    """执行 3 大筛选逻辑"""
    try:
        ticker = yf.Ticker(symbol)
        # 获取2年数据确保 MA250 准确
        df = ticker.history(period="2y")
        if len(df) < 250: return None
        
        # 1. 低位识别 (技术面)
        df['MA250'] = df['Close'].rolling(window=250).mean()
        df['RSI'] = calculate_rsi(df['Close'])
        
        latest = df.iloc[-1]
        close = latest['Close']
        ma250 = latest['MA250']
        rsi = latest['RSI']
        
        # 核心硬指标：股价 < 250日均线的 80% 且 RSI < 35
        is_low_position = (close < ma250 * ma_ratio_threshold) and (rsi < rsi_threshold)
        
        if is_low_position:
            # 2. 资金面 (Money Flow)
            df['MFI'] = calculate_mfi(df)
            mfi = df['MFI'].iloc[-1]
            mfi_prev = df['MFI'].iloc[-2]
            
            # 判断资金流向：MFI 较高或正在回升
            money_flow_active = mfi > 40 or mfi > mfi_prev
            
            if money_flow_active:
                # 3. 机构动向 (通过 info 接口确认)
                # 提示：由于 info 接口慢，只对符合前两项的股票查询
                inst_percent = get_inst_holdings(symbol)
                
                return {
                    '代码': symbol,
                    '行业': sector_map.get(symbol, "未知"),
                    '价格': round(close, 2),
                    '年线(MA250)': round(ma250, 2),
                    '乖离率%': round((close - ma250) / ma250 * 100, 2),
                    'RSI': round(rsi, 2),
                    'MFI(资金流)': round(mfi, 2),
                    '机构持仓%': inst_percent
                }
    except:
        pass
    return None

# --- 3. 界面逻辑 ---

# 初始化数据
sp500_df = get_sp500_data()
sectors = sorted(sp500_df['GICS Sector'].unique().tolist())
sector_map = dict(zip(sp500_df['Symbol'], sp500_df['GICS Sector']))

st.sidebar.header("🔍 筛选条件设置")

# 1. 行业筛选
selected_sector = st.sidebar.selectbox("1. 选择行业板块", ["全选 (S&P 500)"] + sectors)

# 2. 低位参数
st.sidebar.subheader("2. 低位识别参数")
ma_limit = st.sidebar.slider("股价低于年线比例 (%)", 50, 100, 80, help="默认 80% 即股价处于年线 8 折以下")
rsi_limit = st.sidebar.slider("RSI (14日) 阈值", 10, 50, 35)

# 筛选代码列表
if selected_sector == "全选 (S&P 500)":
    ticker_list = sp500_df['Symbol'].tolist()
else:
    ticker_list = sp500_df[sp500_df['GICS Sector'] == selected_sector]['Symbol'].tolist()

start_scan = st.sidebar.button("🚀 开始扫描美股", use_container_width=True)

# --- 4. 主展示区 ---

st.title("🎯 美股底部反转 & 机构资金筛选器")
st.info(f"当前模式：**{selected_sector}** | 指标：**Price < {ma_limit}% MA250** & **RSI < {rsi_limit}**")

if start_scan:
    total = len(ticker_list)
    results = []
    
    progress_bar = st.progress(0)
    status_text = st.empty()
    
    start_time = time.time()
    
    for i, symbol in enumerate(ticker_list):
        # 处理 yfinance 代码格式
        yf_symbol = symbol.replace('.', '-')
        status_text.text(f"分析中 ({i+1}/{total}): {symbol}")
        
        res = check_stock_strategy(yf_symbol, ma_limit/100.0, rsi_limit)
        if res:
            res['代码'] = symbol
            results.append(res)
        
        progress_bar.progress((i + 1) / total)
        # 避免请求过快
        if i % 20 == 0: time.sleep(0.05)

    duration = round(time.time() - start_time, 1)
    status_text.success(f"扫描完成！耗时 {duration} 秒。")

    if results:
        df_res = pd.DataFrame(results)
        
        # 指标卡片
        c1, c2, c3 = st.columns(3)
        c1.metric("符合共振股数", len(results))
        c2.metric("平均机构占比", f"{round(df_res['机构持仓%'].mean(), 2)}%")
        c3.metric("最低RSI标的", df_res.sort_values('RSI').iloc[0]['代码'])

        st.write("### 🔍 底部共振个股清单")
        st.write("表格按 **MFI (资金流量)** 降序排列，数值越高代表底部承接力越强。")
        
        # 格式化展示
        st.dataframe(
            df_res.sort_values('MFI(资金流)', ascending=False).style.background_gradient(subset=['MFI(资金流)', '机构持仓%'], cmap='Greens'),
            use_container_width=True,
            hide_index=True
        )

        # 散点分析图
        st.write("### 📈 机构持仓 vs 乖离率分布")
        fig = go.Figure(data=[go.Scatter(
            x=df_res['乖离率%'], 
            y=df_res['机构持仓%'],
            mode='markers+text',
            text=df_res['代码'],
            textposition="top center",
            marker=dict(size=df_res['MFI(资金流)']/2, color=df_res['MFI(资金流)'], colorscale='Viridis', showscale=True)
        )])
        fig.update_layout(xaxis_title="乖离率 % (负值越大越超跌)", yaxis_title="机构持仓占比 %", template="plotly_white")
        st.plotly_chart(fig, use_container_width=True)

        csv = df_res.to_csv(index=False).encode('utf_8_sig')
        st.download_button("📥 导出筛选结果 (CSV)", csv, f"US_Bottom_Scan_{datetime.now().strftime('%Y%m%d')}.csv")
        
    else:
        st.warning("☹️ 当前条件下未发现符合“超跌+低RSI+资金流入”的股票。请尝试放宽行业或指标限制。")
else:
    st.divider()
    col1, col2 = st.columns(2)
    with col1:
        st.write("### 📖 指标定义")
        st.markdown("""
        - **MA250 乖离率**：股价与年线的距离。-20% 以下代表极度超跌。
        - **MFI (Money Flow Index)**：量价结合指标。在超跌区，MFI 回升通常预示着“聪明钱”在捡筹码。
        - **机构持仓%**：显示有多少股份由共同基金、对冲基金等持有，是美股护盘的主要力量。
        """)
    with col2:
        st.write("### 🛡️ 风险提示")
        st.markdown("""
        - 底部筛选仅代表技术面超跌，不代表不会继续下跌（抄底需谨慎）。
        - 建议结合大盘环境（VIX指数）进行综合判断。
        - 扫描全量 S&P 500 可能耗时较长，推荐按行业逐步扫描。
        """)

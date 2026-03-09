import streamlit as st
import akshare as ak
import pandas as pd
import pandas_ta as ta
import time
from datetime import datetime
import plotly.graph_objects as go

# --- 1. 页面配置 ---
st.set_page_config(
    page_title="A股底部资金共振筛选器",
    page_icon="🎯",
    layout="wide"
)

# 自定义样式：美化卡片和背景
st.markdown("""
    <style>
    .main { background-color: #f8f9fa; }
    .stMetric { background-color: #ffffff; padding: 15px; border-radius: 10px; box-shadow: 0 2px 4px rgba(0,0,0,0.05); }
    </style>
    """, unsafe_allow_html=True)

# --- 2. 核心数据获取函数 ---

@st.cache_data(ttl=86400)
def get_industry_list():
    """获取东方财富行业板块名称列表"""
    try:
        industry_df = ak.stock_board_industry_name_em()
        return industry_df['板块名称'].tolist()
    except:
        return ["半导体", "医疗器械", "汽车零部件", "光伏设备", "酿酒行业"]

@st.cache_data(ttl=3600)
def get_industry_stocks(industry_name):
    """获取指定板块的成份股代码和名称"""
    try:
        df = ak.stock_board_industry_cons_em(symbol=industry_name)
        # 过滤掉北交所，仅保留主板和创业板
        df = df[df['代码'].str.startswith(('60', '00', '30'))]
        return df[['代码', '名称']]
    except:
        return pd.DataFrame()

def check_stock_strategy(symbol, ma_ratio, rsi_threshold):
    """
    判断单只股票是否符合筛选策略：
    1. 价格处于 250 日均线（年线）下方的指定比例
    2. RSI(14) 处于超卖区间
    3. 今日主力资金净流入为正
    """
    try:
        # 抓取 K 线数据
        df = ak.stock_zh_a_hist(symbol=symbol, period="daily", adjust="qfq")
        if len(df) < 250: return None
        
        # 计算技术指标
        df['MA250'] = ta.sma(df['收盘'], length=250)
        df['RSI'] = ta.rsi(df['收盘'], length=14)
        
        latest = df.iloc[-1]
        close, ma250, rsi = latest['收盘'], latest['MA250'], latest['RSI']
        
        # 策略判断 1 & 2
        if (close < ma250 * ma_ratio) and (rsi < rsi_threshold):
            # 策略判断 3: 资金流向
            market = "sh" if symbol.startswith('6') else "sz"
            flow_df = ak.stock_individual_fund_flow(stock=symbol, market=market)
            
            if not flow_df.empty:
                net_inflow = flow_df.iloc[-1]['主力净流入-净额']
                if net_inflow > 0:
                    return {
                        '代码': symbol, '收盘价': close, '年线(MA250)': round(ma250, 2),
                        '乖离率%': round((close - ma250) / ma250 * 100, 2),
                        'RSI14': round(rsi, 2), '主力净流入(万)': round(net_inflow / 10000, 2),
                        '成交额(万)': round(latest['成交额'] / 10000, 2)
                    }
        return None
    except:
        return None

# --- 3. 侧边栏交互 UI ---

st.sidebar.header("⚙️ 筛选参数设置")
selected_ind = st.sidebar.selectbox("1. 选择行业板块", get_industry_list())

ma_pct = st.sidebar.slider("2. 股价低于年线幅度 (%)", 0, 50, 20)
ma_ratio = (100 - ma_pct) / 100.0
rsi_limit = st.sidebar.number_input("3. RSI(14) 低于", 10, 50, 35)

st.sidebar.info("当前资金面要求：今日主力净流入 > 0")
start_button = st.sidebar.button("🚀 开始扫描", use_container_width=True)

# --- 4. 主界面展示逻辑 ---

st.title("🎯 A股底部资金共振筛选器")
st.markdown("> **策略逻辑**：寻找在年线下方大幅超跌、技术面超卖且主力资金开始反手买入的个股。")

if start_button:
    stocks = get_industry_stocks(selected_ind)
    if stocks.empty:
        st.error("无法获取该板块成份股。")
    else:
        total = len(stocks)
        st.subheader(f"📊 正在分析 {selected_ind} 板块 ({total} 只个股)")
        
        progress_bar = st.progress(0)
        status = st.empty()
        results = []
        
        for i, (idx, row) in enumerate(stocks.iterrows()):
            name, code = row['名称'], row['代码']
            status.text(f"分析中 ({i+1}/{total}): {name} ({code})")
            
            res = check_stock_strategy(code, ma_ratio, rsi_limit)
            if res:
                res['名称'] = name
                results.append(res)
            
            progress_bar.progress((i + 1) / total)
            time.sleep(0.05) # 微调防止高频限制
            
        status.success("扫描任务完成！")
        
        if results:
            df = pd.DataFrame(results)[['代码', '名称', '收盘价', '乖离率%', 'RSI14', '主力净流入(万)', '成交额(万)']]
            
            # 数据摘要展示
            c1, c2 = st.columns(2)
            c1.metric("符合条件数", len(results))
            c2.metric("板块平均RSI", round(df['RSI14'].mean(), 2))
            
            # 表格展示
            st.dataframe(df.style.background_gradient(subset=['主力净流入(万)'], cmap='Greens'), 
                         use_container_width=True, hide_index=True)
            
            # 气泡图展示：横轴乖离率，纵轴主力流入，气泡大小RSI
            fig = go.Figure(data=[go.Scatter(
                x=df['乖离率%'], y=df['主力净流入(万)'], mode='markers+text',
                text=df['名称'], textposition="top center",
                marker=dict(size=df['RSI14'], color=df['RSI14'], colorscale='Viridis', showscale=True)
            )])
            fig.update_layout(title="筛选个股分布图（气泡大小代表RSI）", xaxis_title="乖离率 %", yaxis_title="主力净流入 (万)")
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("当前条件下未找到符合条件的个股，可以尝试放宽筛选条件。")
else:
    st.info("👈 请在左侧选择行业并调整参数，然后点击“开始扫描”。")
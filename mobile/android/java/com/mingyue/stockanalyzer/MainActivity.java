package com.mingyue.stockanalyzer;

import android.app.Activity;
import android.graphics.Color;
import android.os.Build;
import android.os.Bundle;
import android.view.View;
import android.view.ViewGroup;
import android.view.Window;
import android.view.WindowManager;
import android.webkit.WebChromeClient;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;

/**
 * 极简 WebView 壳：界面与分析逻辑全部在 assets/index.html 里，本文件只负责承载。
 *
 * 关键点：
 *  1. 页面来自 file:///android_asset/，其 Origin 为 null。行情接口（腾讯 / 东方财富）
 *     本身带 CORS 头，但为保险起见再打开 allowUniversalAccessFromFileURLs。
 *  2. 关掉缩放与滚动条，避免网页被系统二次缩放后布局跑偏。
 *  3. 返回键优先交给网页（用于关闭搜索结果弹层）。
 */
public class MainActivity extends Activity {

    private WebView web;
    private static final String PAGE = "file:///android_asset/index.html";
    private static final int BG = 0xFF0E1218;
    private static final int BAR = 0xFF151A23;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        requestWindowFeature(Window.FEATURE_NO_TITLE);

        web = new WebView(this);
        WebSettings s = web.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);
        s.setDatabaseEnabled(true);
        s.setAllowFileAccess(true);
        s.setAllowContentAccess(true);
        s.setLoadsImagesAutomatically(true);
        s.setSupportZoom(false);
        s.setBuiltInZoomControls(false);
        s.setDisplayZoomControls(false);
        s.setUseWideViewPort(true);
        s.setLoadWithOverviewMode(false);
        s.setCacheMode(WebSettings.LOAD_NO_CACHE);
        s.setTextZoom(100);

        // 允许 file:// 页面发起跨域请求（行情接口）
        try {
            s.setAllowUniversalAccessFromFileURLs(true);
            s.setAllowFileAccessFromFileURLs(true);
        } catch (Throwable ignored) {
            // 个别 ROM 上这两个开关可能被禁用，接口自带 CORS 头仍可正常工作
        }
        if (Build.VERSION.SDK_INT >= 21) {
            try {
                s.setMixedContentMode(WebSettings.MIXED_CONTENT_ALWAYS_ALLOW);
            } catch (Throwable ignored) {
                // 忽略
            }
        }

        web.setBackgroundColor(BG);
        web.setOverScrollMode(View.OVER_SCROLL_NEVER);
        web.setVerticalScrollBarEnabled(false);
        web.setHorizontalScrollBarEnabled(false);
        web.setWebViewClient(new WebViewClient());
        web.setWebChromeClient(new WebChromeClient());

        setContentView(web, new ViewGroup.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.MATCH_PARENT));

        try {
            Window w = getWindow();
            w.addFlags(WindowManager.LayoutParams.FLAG_DRAWS_SYSTEM_BAR_BACKGROUNDS);
            w.setStatusBarColor(BAR);
            w.setNavigationBarColor(BG);
        } catch (Throwable ignored) {
            // 忽略
        }

        if (savedInstanceState == null) {
            web.loadUrl(PAGE);
        } else {
            web.restoreState(savedInstanceState);
            if (web.getUrl() == null) { web.loadUrl(PAGE); }
        }
    }

    @Override
    protected void onSaveInstanceState(Bundle out) {
        super.onSaveInstanceState(out);
        if (web != null) { web.saveState(out); }
    }

    @Override
    public void onBackPressed() {
        if (web != null && web.canGoBack()) {
            web.goBack();
            return;
        }
        super.onBackPressed();
    }

    @Override
    protected void onDestroy() {
        if (web != null) {
            web.setWebChromeClient(null);
            web.setWebViewClient(null);
            web.destroy();
            web = null;
        }
        super.onDestroy();
    }
}

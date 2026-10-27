package com.ehcc.admin;

import android.app.Activity;
import android.app.AlertDialog;
import android.webkit.JsResult;
import android.webkit.WebChromeClient;
import android.app.DownloadManager;
import android.content.Intent;
import android.net.Uri;
import android.os.Bundle;
import android.os.Environment;
import android.webkit.CookieManager;
import android.webkit.URLUtil;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;

public class MainActivity extends Activity {
    private WebView web;

    @Override
    protected void onCreate(Bundle b) {
        super.onCreate(b);
        web = new WebView(this);
        setContentView(web);
        final String home = getString(R.string.app_url);
        final String host = Uri.parse(home).getHost();
        WebSettings s = web.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);
        CookieManager.getInstance().setAcceptCookie(true);
        web.setWebViewClient(new WebViewClient() {
            @Override
            public boolean shouldOverrideUrlLoading(WebView v, WebResourceRequest r) {
                Uri u = r.getUrl();
                if (host != null && host.equals(u.getHost())) return false;
                startActivity(new Intent(Intent.ACTION_VIEW, u));
                return true;
            }
        });
        web.setWebChromeClient(new WebChromeClient() {
            @Override
            public boolean onJsConfirm(WebView v, String url, String msg, JsResult r) {
                new AlertDialog.Builder(MainActivity.this).setMessage(msg)
                    .setPositiveButton(android.R.string.ok, (d, w) -> r.confirm())
                    .setNegativeButton(android.R.string.cancel, (d, w) -> r.cancel())
                    .setOnCancelListener(d -> r.cancel()).show();
                return true;
            }
            @Override
            public boolean onJsAlert(WebView v, String url, String msg, JsResult r) {
                new AlertDialog.Builder(MainActivity.this).setMessage(msg)
                    .setPositiveButton(android.R.string.ok, (d, w) -> r.confirm())
                    .setOnCancelListener(d -> r.cancel()).show();
                return true;
            }
        });
        web.setDownloadListener((url, ua, cd, mime, len) -> {
            DownloadManager.Request req = new DownloadManager.Request(Uri.parse(url));
            req.addRequestHeader("Cookie", CookieManager.getInstance().getCookie(url));
            req.setMimeType(mime);
            req.setNotificationVisibility(DownloadManager.Request.VISIBILITY_VISIBLE_NOTIFY_COMPLETED);
            req.setDestinationInExternalPublicDir(Environment.DIRECTORY_DOWNLOADS,
                URLUtil.guessFileName(url, cd, mime));
            ((DownloadManager) getSystemService(DOWNLOAD_SERVICE)).enqueue(req);
        });
        if (b == null) web.loadUrl(home); else web.restoreState(b);
    }

    @Override protected void onSaveInstanceState(Bundle o) { super.onSaveInstanceState(o); web.saveState(o); }

    @Override public void onBackPressed() {
        if (web.canGoBack()) web.goBack(); else super.onBackPressed();
    }
}

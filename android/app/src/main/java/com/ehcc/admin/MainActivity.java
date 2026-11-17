package com.ehcc.admin;

import android.app.Activity;
import android.content.ContentValues;
import android.content.ClipData;
import android.os.Build;
import android.provider.MediaStore;
import android.webkit.JavascriptInterface;
import java.io.OutputStream;
import android.util.Base64;
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
        web.addJavascriptInterface(new AndroidShareBridge(), "EHCCAndroid");
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

    // A WebView-safe native file share. Keep the APK activity alive and let
    // Android's chooser handle the hand-off to the selected target app.
    private class AndroidShareBridge {
        @JavascriptInterface
        public boolean sharePng(String dataUrl) {
            if (Build.VERSION.SDK_INT < Build.VERSION_CODES.Q || dataUrl == null ||
                    !dataUrl.startsWith("data:image/png;base64,")) return false;
            Uri imageUri = null;
            try {
                byte[] bytes = Base64.decode(dataUrl.substring(dataUrl.indexOf(',') + 1), Base64.DEFAULT);
                ContentValues values = new ContentValues();
                values.put(MediaStore.Downloads.DISPLAY_NAME, "ehcc-players-owing-team.png");
                values.put(MediaStore.Downloads.MIME_TYPE, "image/png");
                values.put(MediaStore.Downloads.RELATIVE_PATH, Environment.DIRECTORY_DOWNLOADS + "/EHCC");
                imageUri = getContentResolver().insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, values);
                if (imageUri == null) return false;
                try (OutputStream stream = getContentResolver().openOutputStream(imageUri)) {
                    if (stream == null) throw new IllegalStateException("Unable to write shared image");
                    stream.write(bytes);
                }
                final Uri sharedImage = imageUri;
                runOnUiThread(() -> {
                    Intent send = new Intent(Intent.ACTION_SEND);
                    send.setType("image/png");
                    send.putExtra(Intent.EXTRA_STREAM, sharedImage);
                    send.setClipData(ClipData.newUri(getContentResolver(), "EHCC players owing the team", sharedImage));
                    send.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);
                    startActivity(Intent.createChooser(send, "Share players owing the team"));
                });
                return true;
            } catch (Exception e) {
                if (imageUri != null) getContentResolver().delete(imageUri, null, null);
                return false;
            }
        }
    }

    @Override protected void onSaveInstanceState(Bundle o) { super.onSaveInstanceState(o); web.saveState(o); }

    @Override public void onBackPressed() {
        if (web.canGoBack()) web.goBack(); else super.onBackPressed();
    }
}

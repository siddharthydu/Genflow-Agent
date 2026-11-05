package app.genflow;

import android.content.Context;
import android.content.SharedPreferences;
import android.security.keystore.KeyGenParameterSpec;
import android.security.keystore.KeyProperties;
import android.util.Base64;
import org.json.JSONObject;
import java.io.*;
import java.net.*;
import java.nio.charset.StandardCharsets;
import java.security.KeyStore;
import javax.crypto.Cipher;
import javax.crypto.KeyGenerator;
import javax.crypto.SecretKey;
import javax.crypto.spec.GCMParameterSpec;

final class Api {
    private final SharedPreferences prefs;
    private String endpoint;
    private String token = "";
    Api(Context context) {
        prefs = context.getSharedPreferences("GenFlow", Context.MODE_PRIVATE);
        endpoint = prefs.getString("endpoint", "");
        try { token = decrypt(prefs.getString("session", "")); } catch (Exception ignored) { clear(); }
    }
    String endpoint() { return endpoint; }
    boolean signedIn() { return !token.isEmpty(); }
    void endpoint(String value) throws Exception {
        URI uri = new URI(value.trim());
        if (!"https".equals(uri.getScheme()) || uri.getHost() == null || uri.getUserInfo() != null
                || uri.getRawQuery() != null || uri.getFragment() != null
                || !(uri.getPath().isEmpty() || uri.getPath().equals("/")))
            throw new IOException("Enter your server's HTTPS origin, for example https://genflow.example.com");
        String next = value.trim().replaceAll("/+$", "");
        if (!next.equals(endpoint)) clear();
        endpoint = next;
        prefs.edit().putString("endpoint", endpoint).apply();
    }
    void login(String password) throws Exception {
        JSONObject input = new JSONObject().put("password", password);
        String next = request("POST", "/api/login", input).getString("token");
        prefs.edit().putString("session", encrypt(next)).apply();
        token = next;
    }
    void clear() { token = ""; prefs.edit().remove("session").apply(); }
    private HttpURLConnection connect(String method, String path) throws Exception {
        HttpURLConnection c = (HttpURLConnection) new URL(endpoint + path).openConnection();
        c.setRequestMethod(method);
        c.setInstanceFollowRedirects(false); // Never forward credentials to another origin.
        c.setConnectTimeout(20000);
        c.setReadTimeout(120000);
        c.setRequestProperty("Accept", "application/json");
        if (!token.isEmpty()) c.setRequestProperty("Authorization", "Bearer " + token);
        return c;
    }
    private void check(HttpURLConnection c) throws Exception {
        int code = c.getResponseCode();
        if (code < 200 || code >= 300) {
            String error = "Server returned " + code;
            InputStream stream = c.getErrorStream();
            if (stream != null) try (stream) {
                String body = new String(read(stream, 10000), StandardCharsets.UTF_8);
                try { error = new JSONObject(body).optString("error", error); } catch (Exception ignored) { }
            }
            if (code == 401) clear();
            throw new IOException(error);
        }
    }
    JSONObject request(String method, String path, JSONObject body) throws Exception {
        HttpURLConnection c = connect(method, path);
        try {
            if (body != null) {
                byte[] bytes = body.toString().getBytes(StandardCharsets.UTF_8);
                c.setDoOutput(true);
                c.setRequestProperty("Content-Type", "application/json");
                c.setFixedLengthStreamingMode(bytes.length);
                try (OutputStream out = c.getOutputStream()) { out.write(bytes); }
            }
            check(c);
            try (InputStream in = c.getInputStream()) {
                return new JSONObject(new String(read(in, 8_000_000), StandardCharsets.UTF_8));
            }
        } finally { c.disconnect(); }
    }
    void upload(String path, File file, String mime) throws Exception {
        HttpURLConnection c = connect("POST", path);
        try {
            c.setDoOutput(true);
            c.setFixedLengthStreamingMode(file.length());
            c.setRequestProperty("Content-Type", mime);
            try (InputStream in = new FileInputStream(file); OutputStream out = c.getOutputStream()) { copy(in, out); }
            check(c);
        } finally { c.disconnect(); }
    }
    void download(String path, OutputStream out) throws Exception {
        HttpURLConnection c = connect("GET", path);
        try { check(c); try (InputStream in = c.getInputStream()) { copy(in, out); } }
        finally { c.disconnect(); }
    }
    java.util.Map<String,String> videoHeaders() { return java.util.Collections.singletonMap("Authorization", "Bearer " + token); }
    private static void copy(InputStream in, OutputStream out) throws IOException {
        byte[] buffer = new byte[65536]; int n;
        while ((n = in.read(buffer)) != -1) out.write(buffer, 0, n);
    }
    private static byte[] read(InputStream in, int maximum) throws IOException {
        ByteArrayOutputStream out = new ByteArrayOutputStream(); byte[] buffer = new byte[8192]; int n;
        while ((n = in.read(buffer)) != -1) { if (out.size()+n > maximum) throw new IOException("Response too large"); out.write(buffer,0,n); }
        return out.toByteArray();
    }
    private SecretKey key() throws Exception {
        KeyStore store = KeyStore.getInstance("AndroidKeyStore");
        store.load(null);
        if (store.containsAlias("GenFlowSession")) return (SecretKey) store.getKey("GenFlowSession", null);
        KeyGenerator generator = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore");
        generator.init(new KeyGenParameterSpec.Builder("GenFlowSession", KeyProperties.PURPOSE_ENCRYPT | KeyProperties.PURPOSE_DECRYPT)
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM).setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE).build());
        return generator.generateKey();
    }
    private String encrypt(String value) throws Exception {
        Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
        cipher.init(Cipher.ENCRYPT_MODE, key());
        return Base64.encodeToString(cipher.getIV(), Base64.NO_WRAP) + ":" +
                Base64.encodeToString(cipher.doFinal(value.getBytes(StandardCharsets.UTF_8)), Base64.NO_WRAP);
    }
    private String decrypt(String value) throws Exception {
        if (value.isEmpty()) return "";
        String[] data = value.split(":");
        Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
        cipher.init(Cipher.DECRYPT_MODE, key(), new GCMParameterSpec(128, Base64.decode(data[0], Base64.NO_WRAP)));
        return new String(cipher.doFinal(Base64.decode(data[1], Base64.NO_WRAP)), StandardCharsets.UTF_8);
    }
}

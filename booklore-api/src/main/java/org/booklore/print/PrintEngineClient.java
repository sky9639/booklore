package org.booklore.print;

import java.util.Map;
import org.springframework.http.ResponseEntity;
import org.springframework.http.client.SimpleClientHttpRequestFactory;
import org.springframework.stereotype.Service;
import org.springframework.web.client.RestTemplate;

@Service
public class PrintEngineClient {

    private static final String BASE_URL = "http://print-engine:5000";

    /**
     * 普通接口（init / preview / generate / saveParams）
     * readTimeout = 45s
     */
    private final RestTemplate restTemplate = buildRestTemplate(10_000, 45_000);

    /**
     * AI 生成专用（FLUX Outpainting 单张约 2-5 分钟）
     * readTimeout = 300s
     *
     * 注：旧方案 Claude + OpenAI 约 60-90s，
     *     FLUX 本地生成更慢，保守给 300s
     */
    private final RestTemplate aiRestTemplate = buildRestTemplate(
        10_000,
        300_000
    );

    private static RestTemplate buildRestTemplate(
        int connectTimeout,
        int readTimeout
    ) {
        SimpleClientHttpRequestFactory factory =
            new SimpleClientHttpRequestFactory();
        factory.setConnectTimeout(connectTimeout);
        factory.setReadTimeout(readTimeout);
        return new RestTemplate(factory);
    }

    public Map initWorkspace(Map requestBody) {
        try {
            ResponseEntity<Map> response = restTemplate.postForEntity(
                BASE_URL + "/workspace/init",
                requestBody,
                Map.class
            );
            return response.getBody();
        } catch (Exception e) {
            return Map.of("status", "error", "message", e.getMessage());
        }
    }

    public Map preview(Map requestBody) {
        try {
            ResponseEntity<Map> response = restTemplate.postForEntity(
                BASE_URL + "/preview",
                requestBody,
                Map.class
            );
            return response.getBody();
        } catch (Exception e) {
            return Map.of("status", "error", "message", e.getMessage());
        }
    }

    public Map generate(Map requestBody) {
        try {
            ResponseEntity<Map> response = restTemplate.postForEntity(
                BASE_URL + "/generate",
                requestBody,
                Map.class
            );
            return response.getBody();
        } catch (Exception e) {
            return Map.of("status", "error", "message", e.getMessage());
        }
    }

    public Map saveParams(Map<String, Object> payload) {
        try {
            ResponseEntity<Map> response = restTemplate.postForEntity(
                BASE_URL + "/workspace/params",
                payload,
                Map.class
            );
            return response.getBody();
        } catch (Exception e) {
            return Map.of("status", "error", "message", e.getMessage());
        }
    }

    /**
     * 启动 AI 生成任务（异步），立即返回 {"task_id": "..."}
     * 前端通过 SSE 接口订阅进度
     */
    public Map aiGenerateStart(Map<String, Object> payload) {
        try {
            ResponseEntity<Map> response = restTemplate.postForEntity(
                BASE_URL + "/workspace/ai-generate/start",
                payload,
                Map.class
            );
            Map body = response.getBody();
            if (body == null) throw new RuntimeException(
                "aiGenerateStart returned null"
            );
            return body;
        } catch (Exception e) {
            throw new RuntimeException(
                "aiGenerateStart failed: " + e.getMessage(),
                e
            );
        }
    }

    /**
     * AI 生成书脊 / 封底
     *
     * print-engine /ai-generate 直接返回 PNG bytes（Content-Type: image/png）
     * Java 侧收到 bytes 后由 PrintController.aiGenerateMaterial() 负责：
     *   - 命名文件：ai_{target}_{timestamp}.png
     *   - 保存到 .print/{target}/
     *   - 更新 workspace.json
     *
     * 使用独立的 aiRestTemplate（readTimeout = 300s）
     */
    public byte[] aiGenerate(Map<String, Object> payload) {
        try {
            ResponseEntity<byte[]> response = aiRestTemplate.postForEntity(
                BASE_URL + "/ai-generate",
                payload,
                byte[].class
            );
            byte[] body = response.getBody();
            if (body == null || body.length == 0) {
                throw new RuntimeException(
                    "AI generate returned empty response"
                );
            }
            return body;
        } catch (Exception e) {
            throw new RuntimeException(
                "AI generate failed: " + e.getMessage(),
                e
            );
        }
    }
}

package org.booklore.print;

import java.util.Map;
import org.springframework.core.io.ByteArrayResource;
import org.springframework.http.HttpEntity;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.http.client.SimpleClientHttpRequestFactory;
import org.springframework.stereotype.Service;
import org.springframework.util.LinkedMultiValueMap;
import org.springframework.util.MultiValueMap;
import org.springframework.web.client.RestTemplate;
import org.springframework.web.multipart.MultipartFile;

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

    public Map uploadMaterial(
        String category,
        Map<String, Object> payload,
        MultipartFile file
    ) {
        try {
            HttpHeaders headers = new HttpHeaders();
            headers.setContentType(MediaType.MULTIPART_FORM_DATA);

            MultiValueMap<String, Object> body = new LinkedMultiValueMap<>();
            payload.forEach(body::add);
            body.add(
                "file",
                new ByteArrayResource(file.getBytes()) {
                    @Override
                    public String getFilename() {
                        return file.getOriginalFilename();
                    }
                }
            );

            HttpEntity<MultiValueMap<String, Object>> request = new HttpEntity<>(body, headers);
            ResponseEntity<Map> response = restTemplate.postForEntity(
                BASE_URL + "/workspace/upload/" + category,
                request,
                Map.class
            );
            return response.getBody();
        } catch (Exception e) {
            throw new RuntimeException("uploadMaterial failed: " + e.getMessage(), e);
        }
    }

    public Map selectMaterial(Map<String, Object> payload) {
        try {
            ResponseEntity<Map> response = restTemplate.postForEntity(
                BASE_URL + "/workspace/material/select",
                payload,
                Map.class
            );
            return response.getBody();
        } catch (Exception e) {
            throw new RuntimeException("selectMaterial failed: " + e.getMessage(), e);
        }
    }

    public Map deleteMaterial(Map<String, Object> payload) {
        try {
            ResponseEntity<Map> response = restTemplate.postForEntity(
                BASE_URL + "/workspace/material/delete",
                payload,
                Map.class
            );
            return response.getBody();
        } catch (Exception e) {
            throw new RuntimeException("deleteMaterial failed: " + e.getMessage(), e);
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
     * 获取PDF信息（尺寸、页数等）
     */
    public Map getPdfInfo(Map<String, Object> payload) {
        try {
            ResponseEntity<Map> response = restTemplate.postForEntity(
                BASE_URL + "/pdf/info",
                payload,
                Map.class
            );
            return response.getBody();
        } catch (Exception e) {
            return Map.of("success", false, "error", e.getMessage());
        }
    }

    /**
     * 启动PDF格式化任务
     */
    public Map startPdfResize(Map<String, Object> payload) {
        try {
            ResponseEntity<Map> response = restTemplate.postForEntity(
                BASE_URL + "/pdf/resize/start",
                payload,
                Map.class
            );
            Map body = response.getBody();
            if (body == null) throw new RuntimeException("startPdfResize returned null");
            return body;
        } catch (Exception e) {
            throw new RuntimeException("startPdfResize failed: " + e.getMessage(), e);
        }
    }

    /**
     * PDF格式化进度（SSE流）
     */
    public org.springframework.web.servlet.mvc.method.annotation.SseEmitter streamPdfResizeProgress(String taskId) {
        org.springframework.web.servlet.mvc.method.annotation.SseEmitter emitter =
            new org.springframework.web.servlet.mvc.method.annotation.SseEmitter(600_000L);

        new Thread(() -> {
            try {
                java.net.URL url = new java.net.URL(BASE_URL + "/pdf/resize/progress/" + taskId);
                java.net.HttpURLConnection conn = (java.net.HttpURLConnection) url.openConnection();
                conn.setRequestMethod("GET");
                conn.setConnectTimeout(10_000);
                conn.setReadTimeout(600_000);

                java.io.BufferedReader reader = new java.io.BufferedReader(
                    new java.io.InputStreamReader(conn.getInputStream())
                );

                String line;
                while ((line = reader.readLine()) != null) {
                    if (line.startsWith("data: ")) {
                        String data = line.substring(6);
                        emitter.send(
                            org.springframework.web.servlet.mvc.method.annotation.SseEmitter.event()
                                .data(data)
                        );
                    } else if (line.startsWith(": ")) {
                        // 心跳，忽略
                    }
                }

                emitter.complete();
                reader.close();
            } catch (Exception e) {
                emitter.completeWithError(e);
            }
        }).start();

        return emitter;
    }

    /**
     * 生成 Gemini 展开图（返回临时预览图和初始裁切线）
     * 使用 aiRestTemplate（readTimeout = 300s）
     */
    public Map generateSpread(Map<String, Object> payload) {
        try {
            ResponseEntity<Map> response = aiRestTemplate.postForEntity(
                BASE_URL + "/workspace/ai-generate/spread",
                payload,
                Map.class
            );
            Map body = response.getBody();
            if (body == null) throw new RuntimeException("generateSpread returned null");
            return body;
        } catch (Exception e) {
            throw new RuntimeException("generateSpread failed: " + e.getMessage(), e);
        }
    }

    /**
     * 保存裁切后的书脊和封底
     */
    public Map saveCroppedMaterials(Map<String, Object> payload) {
        try {
            ResponseEntity<Map> response = restTemplate.postForEntity(
                BASE_URL + "/workspace/ai-generate/crop",
                payload,
                Map.class
            );
            Map body = response.getBody();
            if (body == null) throw new RuntimeException("saveCroppedMaterials returned null");
            return body;
        } catch (Exception e) {
            throw new RuntimeException("saveCroppedMaterials failed: " + e.getMessage(), e);
        }
    }

    public Map discardAiCropDraft(Map<String, Object> payload) {
        try {
            ResponseEntity<Map> response = restTemplate.postForEntity(
                BASE_URL + "/workspace/ai-generate/discard",
                payload,
                Map.class
            );
            Map body = response.getBody();
            if (body == null) throw new RuntimeException("discardAiCropDraft returned null");
            return body;
        } catch (Exception e) {
            throw new RuntimeException("discardAiCropDraft failed: " + e.getMessage(), e);
        }
    }

    public Map deleteAiCropHistory(Map<String, Object> payload) {
        try {
            ResponseEntity<Map> response = restTemplate.postForEntity(
                BASE_URL + "/workspace/ai-generate/history/delete",
                payload,
                Map.class
            );
            Map body = response.getBody();
            if (body == null) throw new RuntimeException("deleteAiCropHistory returned null");
            return body;
        } catch (Exception e) {
            throw new RuntimeException("deleteAiCropHistory failed: " + e.getMessage(), e);
        }
    }
}

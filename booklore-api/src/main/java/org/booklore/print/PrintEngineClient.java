package org.booklore.print;

import org.springframework.http.ResponseEntity;
import org.springframework.stereotype.Service;
import org.springframework.web.client.RestTemplate;

import java.util.Map;

@Service
public class PrintEngineClient {

    private final RestTemplate restTemplate = new RestTemplate();

    private static final String BASE_URL = "http://print-engine:5000";

    public Map preview(Map requestBody) {
        try {
            ResponseEntity<Map> response =
                    restTemplate.postForEntity(BASE_URL + "/preview", requestBody, Map.class);
            return response.getBody();
        } catch (Exception e) {
            return Map.of(
                    "status", "error",
                    "message", e.getMessage()
            );
        }
    }

    public Map generate(Map requestBody) {
        try {
            ResponseEntity<Map> response =
                    restTemplate.postForEntity(BASE_URL + "/generate", requestBody, Map.class);
            return response.getBody();
        } catch (Exception e) {
            return Map.of(
                    "status", "error",
                    "message", e.getMessage()
            );
        }
    }
}
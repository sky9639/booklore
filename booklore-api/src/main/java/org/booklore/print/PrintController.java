package org.booklore.print;

import lombok.RequiredArgsConstructor;
import org.booklore.model.entity.BookEntity;
import org.booklore.print.dto.PrintRequest;
import org.booklore.repository.BookRepository;
import org.springframework.core.io.InputStreamResource;
import org.springframework.core.io.Resource;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

import java.io.File;
import java.io.FileInputStream;
import java.nio.file.Path;
import java.util.Map;

@RestController
@RequestMapping("/api/print")
@RequiredArgsConstructor
public class PrintController {

    private final PrintEngineClient client;
    private final BookRepository bookRepository;

    /**
     * 生成拼版预览
     */
    @PostMapping("/{bookId}/preview")
    public ResponseEntity<?> preview(
            @PathVariable Long bookId,
            @RequestBody PrintRequest request
    ) {

        BookEntity book = bookRepository.findById(bookId)
                .orElseThrow(() -> new RuntimeException("Book not found"));

        Path fullPath = book.getFullFilePath();

        if (fullPath == null) {
            return ResponseEntity.badRequest()
                    .body(Map.of("error", "Book file path could not be resolved"));
        }

        Map<String, Object> payload = Map.of(
                "book_path", fullPath.toString(),
                "paper_thickness", request.getPaperThickness(),
                "page_count", request.getPageCount(),
                "spine_mode", request.getSpineMode(),
                "back_mode", request.getBackMode()
        );

        Map result = client.preview(payload);

        return ResponseEntity.ok(result);
    }

    /**
     * 生成最终 PDF
     */
    @PostMapping("/{bookId}/pdf")
    public ResponseEntity<?> generatePdf(
            @PathVariable Long bookId,
            @RequestBody PrintRequest request
    ) {

        BookEntity book = bookRepository.findById(bookId)
                .orElseThrow(() -> new RuntimeException("Book not found"));

        Path fullPath = book.getFullFilePath();

        if (fullPath == null) {
            return ResponseEntity.badRequest()
                    .body(Map.of("error", "Book file path could not be resolved"));
        }

        Map<String, Object> payload = Map.of(
                "book_path", fullPath.toString(),
                "paper_thickness", request.getPaperThickness(),
                "page_count", request.getPageCount(),
                "spine_mode", request.getSpineMode(),
                "back_mode", request.getBackMode()
        );

        Map result = client.generate(payload);

        return ResponseEntity.ok(result);
    }

    /**
     * 下载 PDF（安全版本）
     */
    @GetMapping("/pdf")
    public ResponseEntity<Resource> downloadPdf(@RequestParam String path) {

        try {
            File file = new File(path);

            if (!file.exists() || !file.getName().endsWith(".pdf")) {
                return ResponseEntity.notFound().build();
            }

            InputStreamResource resource =
                    new InputStreamResource(new FileInputStream(file));

            return ResponseEntity.ok()
                    .header(HttpHeaders.CONTENT_DISPOSITION,
                            "attachment; filename=" + file.getName())
                    .contentLength(file.length())
                    .contentType(MediaType.APPLICATION_PDF)
                    .body(resource);

        } catch (Exception e) {
            return ResponseEntity.internalServerError().build();
        }
    }
}
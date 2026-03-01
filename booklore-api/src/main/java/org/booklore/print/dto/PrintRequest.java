package org.booklore.print.dto;

import lombok.Data;

@Data
public class PrintRequest {

    /**
     * 书脊模式：auto / manual
     */
    private String spineMode = "auto";

    /**
     * 封底模式：auto / manual
     */
    private String backMode = "auto";

    /**
     * 纸张厚度（mm）
     */
    private Double paperThickness = 0.06;

    /**
     * 页数（可选，null则自动读取PDF）
     */
    private Integer pageCount;
}
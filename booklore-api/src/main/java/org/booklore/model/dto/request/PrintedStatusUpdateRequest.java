package org.booklore.model.dto.request;

import jakarta.validation.constraints.NotNull;

public record PrintedStatusUpdateRequest(
        @NotNull Long bookId,
        @NotNull Boolean printed
) {}
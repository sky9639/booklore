def calculate_spine_width(page_count: int, paper_thickness_mm: float) -> float:
    return round(page_count * paper_thickness_mm, 2)
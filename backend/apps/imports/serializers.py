from __future__ import annotations

from rest_framework import serializers

from apps.imports.models import ImportJob, ImportRow


class ImportRowErrorSerializer(serializers.ModelSerializer):
    sourceLineNo = serializers.IntegerField(source="source_line_no")
    errorCode = serializers.CharField(source="error_code", allow_null=True)
    errorDetail = serializers.CharField(source="error_detail")

    class Meta:
        model = ImportRow
        fields = ["sourceLineNo", "errorCode", "errorDetail"]


class ImportSummarySerializer(serializers.ModelSerializer):
    jobId = serializers.UUIDField(source="id")
    fileName = serializers.CharField(source="original_filename")
    fileSha256 = serializers.CharField(source="file_sha256")
    totalRows = serializers.IntegerField(source="total_rows")
    processedRows = serializers.IntegerField(source="processed_rows")
    validRows = serializers.IntegerField(source="valid_rows")
    invalidRows = serializers.IntegerField(source="invalid_rows")
    needsReviewCount = serializers.IntegerField(source="needs_review_count")
    createdAt = serializers.DateTimeField(source="created_at")

    class Meta:
        model = ImportJob
        fields = [
            "jobId",
            "status",
            "fileName",
            "fileSha256",
            "totalRows",
            "processedRows",
            "validRows",
            "invalidRows",
            "needsReviewCount",
            "attempts",
            "createdAt",
        ]


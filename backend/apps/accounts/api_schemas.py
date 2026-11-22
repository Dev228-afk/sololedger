from __future__ import annotations

from rest_framework import serializers


class ApiAccountSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    displayName = serializers.CharField()
    timezone = serializers.CharField()


class DemoAccountsListResponseSerializer(serializers.Serializer):
    items = ApiAccountSerializer(many=True)


class DemoSessionRequestSerializer(serializers.Serializer):
    accountId = serializers.UUIDField()


class DemoSessionResponseSerializer(serializers.Serializer):
    account = ApiAccountSerializer(allow_null=True)
    csrfToken = serializers.CharField(allow_null=True)


class HealthResponseSerializer(serializers.Serializer):
    status = serializers.CharField()
    version = serializers.CharField()
    dependencies = serializers.DictField(child=serializers.CharField())


class ApiCategorySerializer(serializers.Serializer):
    id = serializers.UUIDField()
    code = serializers.CharField()
    name = serializers.CharField()
    kind = serializers.ChoiceField(choices=["EXPENSE", "INCOME", "TRANSFER"])
    sortOrder = serializers.IntegerField()


class CategoriesListResponseSerializer(serializers.Serializer):
    items = ApiCategorySerializer(many=True)


class MappingConfigSerializer(serializers.Serializer):
    postedDateColumn = serializers.CharField()
    descriptionColumn = serializers.CharField()
    amountMode = serializers.ChoiceField(choices=["DEBIT_CREDIT", "SIGNED_AMOUNT"])
    debitColumn = serializers.CharField(allow_null=True, required=False)
    creditColumn = serializers.CharField(allow_null=True, required=False)
    amountColumn = serializers.CharField(allow_null=True, required=False)
    currencyColumn = serializers.CharField(allow_null=True, required=False)
    fixedCurrency = serializers.CharField(allow_null=True, required=False)
    transactionIdColumn = serializers.CharField(allow_null=True, required=False)
    dateFormat = serializers.CharField()
    decimalSeparator = serializers.CharField()
    headerRow = serializers.IntegerField()


class ImportPreviewResponseSerializer(serializers.Serializer):
    uploadToken = serializers.UUIDField()
    fileName = serializers.CharField()
    sha256 = serializers.CharField()
    headers = serializers.ListField(child=serializers.CharField())
    previewRows = serializers.ListField(child=serializers.DictField(child=serializers.CharField()))
    suggestedMapping = MappingConfigSerializer()
    expiresAt = serializers.DateTimeField()


class ImportCreateRequestSerializer(serializers.Serializer):
    uploadToken = serializers.UUIDField()
    mapping = MappingConfigSerializer()


class ImportAcceptedResponseSerializer(serializers.Serializer):
    jobId = serializers.UUIDField()
    status = serializers.CharField()
    statusUrl = serializers.CharField(required=False)


class ApiImportSummarySerializer(serializers.Serializer):
    jobId = serializers.UUIDField()
    status = serializers.ChoiceField(
        choices=["QUEUED", "VALIDATING", "PROCESSING", "AWAITING_REVIEW", "COMPLETED", "FAILED", "CANCELED"]
    )
    fileName = serializers.CharField()
    fileSha256 = serializers.CharField()
    totalRows = serializers.IntegerField()
    processedRows = serializers.IntegerField()
    validRows = serializers.IntegerField()
    invalidRows = serializers.IntegerField()
    needsReviewCount = serializers.IntegerField()
    attempts = serializers.IntegerField()
    createdAt = serializers.DateTimeField()


class ImportsListResponseSerializer(serializers.Serializer):
    items = ApiImportSummarySerializer(many=True)
    nextCursor = serializers.CharField(allow_null=True)


class ApiImportRowErrorSerializer(serializers.Serializer):
    sourceLineNo = serializers.IntegerField()
    errorCode = serializers.CharField(allow_null=True)
    errorDetail = serializers.CharField()


class ImportDetailResponseSerializer(ApiImportSummarySerializer):
    phaseLabel = serializers.CharField()
    errorCode = serializers.CharField(allow_null=True)
    errorMessage = serializers.CharField(allow_null=True)
    canRetry = serializers.BooleanField()
    canCancel = serializers.BooleanField()
    startedAt = serializers.DateTimeField(allow_null=True)
    finishedAt = serializers.DateTimeField(allow_null=True)
    errors = ApiImportRowErrorSerializer(many=True)


class ApiTransactionSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    importJobId = serializers.UUIDField()
    postedDate = serializers.DateField()
    description = serializers.CharField()
    merchant = serializers.CharField()
    signedAmount = serializers.CharField()
    currency = serializers.CharField()
    externalRef = serializers.CharField(allow_null=True)
    categoryCode = serializers.CharField()
    categoryName = serializers.CharField()
    categoryKind = serializers.CharField()
    categorySource = serializers.ChoiceField(
        choices=["USER_RULE", "KEYWORD", "LLM", "FALLBACK", "USER_REVIEW"]
    )
    confidence = serializers.CharField(allow_null=True)
    reviewStatus = serializers.ChoiceField(choices=["SUGGESTED", "NEEDS_REVIEW", "APPROVED"])
    duplicateCandidate = serializers.BooleanField()
    explanationCode = serializers.CharField(allow_null=True)
    version = serializers.IntegerField()


class TransactionsListResponseSerializer(serializers.Serializer):
    items = ApiTransactionSerializer(many=True)
    nextCursor = serializers.CharField(allow_null=True)
    totalCount = serializers.IntegerField()


class TransactionReviewRequestSerializer(serializers.Serializer):
    version = serializers.IntegerField()
    decision = serializers.ChoiceField(choices=["ACCEPT", "CHANGE"])
    categoryCode = serializers.CharField(required=False, allow_null=True)
    rememberMerchant = serializers.BooleanField(required=False, default=False)


class ApiReviewDecisionSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    transactionId = serializers.UUIDField()
    previousCategoryCode = serializers.CharField()
    newCategoryCode = serializers.CharField()
    previousStatus = serializers.CharField()
    decision = serializers.ChoiceField(choices=["ACCEPT", "CHANGE"])
    createdAt = serializers.DateTimeField()


class TransactionReviewResponseSerializer(serializers.Serializer):
    transaction = ApiTransactionSerializer()
    reviewDecision = ApiReviewDecisionSerializer()


class BulkReviewItemRequestSerializer(serializers.Serializer):
    transactionId = serializers.UUIDField()
    version = serializers.IntegerField()
    decision = serializers.ChoiceField(choices=["ACCEPT", "CHANGE"])
    categoryCode = serializers.CharField(required=False, allow_null=True)
    rememberMerchant = serializers.BooleanField(required=False, default=False)


class BulkReviewRequestSerializer(serializers.Serializer):
    items = BulkReviewItemRequestSerializer(many=True)


class BulkReviewResponseSerializer(serializers.Serializer):
    accepted = ApiTransactionSerializer(many=True)
    conflicts = serializers.ListField(child=serializers.DictField())


class ApiMerchantRuleSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    merchantKey = serializers.CharField()
    categoryCode = serializers.CharField()
    categoryName = serializers.CharField()
    priority = serializers.IntegerField()
    active = serializers.BooleanField()
    approvedAt = serializers.DateTimeField()
    version = serializers.IntegerField()


class MerchantRulesListResponseSerializer(serializers.Serializer):
    items = ApiMerchantRuleSerializer(many=True)
    nextCursor = serializers.CharField(allow_null=True)


class MerchantRulePatchRequestSerializer(serializers.Serializer):
    version = serializers.IntegerField()
    categoryCode = serializers.CharField(required=False, allow_null=True)
    active = serializers.BooleanField(required=False)
    priority = serializers.IntegerField(required=False)


class MerchantRulePatchResponseSerializer(serializers.Serializer):
    rule = ApiMerchantRuleSerializer()


class ReportCategoryTotalSerializer(serializers.Serializer):
    code = serializers.CharField()
    name = serializers.CharField()
    netSpend = serializers.CharField()


class ReportMonthEntrySerializer(serializers.Serializer):
    month = serializers.CharField()
    byCategory = ReportCategoryTotalSerializer(many=True)
    netSpend = serializers.CharField()
    totalCredits = serializers.CharField()
    totalDebits = serializers.CharField()


class MonthlyReportResponseSerializer(serializers.Serializer):
    currency = serializers.CharField()
    months = ReportMonthEntrySerializer(many=True)
    categoryTotals = ReportCategoryTotalSerializer(many=True)


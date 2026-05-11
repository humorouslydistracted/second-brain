package com.secondbrain.app.ui.home

import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.core.*
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.LocalClipboardManager
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.navigation.NavHostController
import com.secondbrain.app.AppStatusBus
import com.secondbrain.app.data.DatabaseHolder
import com.secondbrain.app.diag.formatTimestampForDisplay
import com.secondbrain.app.orchestrator.RequestLogDao
import com.secondbrain.app.orchestrator.Tag
import com.secondbrain.app.ui.common.HighlightBus
import org.json.JSONObject
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun HomeScreen(navController: NavHostController? = null, vm: HomeViewModel = viewModel()) {
    val state by vm.state.collectAsState()
    val clipboard = LocalClipboardManager.current
    val scope = rememberCoroutineScope()

    LaunchedEffect(state.notices) {
        val notices = vm.consumeNotices()
        notices.forEach { AppStatusBus.emit(it) }
    }

    LaunchedEffect(state.pending) {
        if (state.pending.none { it.status == PendingStatus.PROCESSING }) {
            vm.refreshTiles()
        }
    }

    val processingItem = state.pending.firstOrNull { it.status == PendingStatus.PROCESSING }

    Scaffold(
        bottomBar = {
            HomeInputBar(
                input = state.input,
                chips = state.chips,
                isProcessing = processingItem != null,
                onChipTap = vm::onChipTap,
                onInputChanged = vm::onInputChanged,
                onSend = vm::onSend,
                onCancel = vm::cancelCurrent,
                onCopyLogs = {
                    scope.launch {
                        val text = withContext(Dispatchers.IO) {
                            RequestLogDao.list(DatabaseHolder.get(), limit = 100)
                                .joinToString("\n---\n") { it.toClipboardBlock() }
                        }
                        clipboard.setText(AnnotatedString(text))
                        AppStatusBus.emit("Copied last 100 requests")
                    }
                },
            )
        },
    ) { padding ->
        Column(
            modifier = Modifier
                .padding(padding)
                .fillMaxSize(),
        ) {
            // ── Fixed section: greeting + tiles (never scrolls) ──────────────
            Column(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(horizontal = 12.dp)
                    .padding(top = 8.dp),
                verticalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                GreetingCard(
                    greeting = state.greeting,
                    summary = state.ambientCurrent,
                    allFacts = state.ambientFacts,
                )
                CompactTilesGrid(
                    summary = state.tileSummary,
                    onTileClick = { route -> navController?.navigate(route) },
                )
                if (state.undo != null) {
                    UndoChip(undo = state.undo, onClick = vm::undoLast)
                }
            }

            // ── Scrollable section: pending + history ────────────────────────
            LazyColumn(
                modifier = Modifier
                    .weight(1f)
                    .fillMaxWidth()
                    .padding(horizontal = 12.dp),
                verticalArrangement = Arrangement.spacedBy(8.dp),
                contentPadding = PaddingValues(vertical = 8.dp),
            ) {
                items(state.pending, key = { "pending-${it.id}" }) { p ->
                    PendingBubble(p, progress = if (p.status == PendingStatus.PROCESSING) state.sendProgress else "")
                }
                state.pendingPrompt?.let { prompt ->
                    item(key = "pending-prompt") {
                        Surface(
                            color = MaterialTheme.colorScheme.tertiaryContainer,
                            modifier = Modifier.fillMaxWidth(),
                        ) {
                            Text(prompt, modifier = Modifier.padding(8.dp), style = MaterialTheme.typography.bodySmall)
                        }
                    }
                }
                if (state.recent.isNotEmpty()) {
                    item(key = "recent-header") {
                        Text(
                            "Recent",
                            style = MaterialTheme.typography.labelMedium,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                            modifier = Modifier.padding(top = 4.dp),
                        )
                    }
                    items(state.recent, key = { "act-${it.id}" }) { item ->
                        HistoryCard(item) { route, rowId ->
                            if (rowId != null) HighlightBus.set(route, rowId)
                            navController?.navigate(route)
                        }
                    }
                }
            }
        }
    }
}

// ───────────────────────────────────────────────────────────────────────────
// Greeting card — expandable to show all ambient facts
// ───────────────────────────────────────────────────────────────────────────

@Composable
private fun GreetingCard(greeting: String, summary: String?, allFacts: List<String>) {
    var expanded by remember { mutableStateOf(false) }
    ElevatedCard(
        modifier = Modifier.fillMaxWidth(),
        colors = CardDefaults.elevatedCardColors(
            containerColor = MaterialTheme.colorScheme.primaryContainer,
        ),
    ) {
        Column {
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .clickable { expanded = !expanded }
                    .padding(start = 16.dp, end = 4.dp, top = 12.dp, bottom = 12.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(3.dp)) {
                    Text(
                        greeting.ifBlank { "Hey there!" },
                        style = MaterialTheme.typography.titleLarge,
                        color = MaterialTheme.colorScheme.onPrimaryContainer,
                    )
                    if (!summary.isNullOrBlank()) {
                        Text(
                            summary,
                            style = MaterialTheme.typography.bodyMedium,
                            color = MaterialTheme.colorScheme.onPrimaryContainer.copy(alpha = 0.8f),
                        )
                    }
                }
                IconButton(onClick = { expanded = !expanded }) {
                    Icon(
                        if (expanded) Icons.Filled.ExpandLess else Icons.Filled.ExpandMore,
                        contentDescription = if (expanded) "Collapse" else "Show all",
                        tint = MaterialTheme.colorScheme.onPrimaryContainer,
                    )
                }
            }
            AnimatedVisibility(visible = expanded) {
                Column(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(start = 16.dp, end = 16.dp, bottom = 12.dp),
                    verticalArrangement = Arrangement.spacedBy(6.dp),
                ) {
                    HorizontalDivider(color = MaterialTheme.colorScheme.onPrimaryContainer.copy(alpha = 0.2f))
                    if (allFacts.isEmpty()) {
                        Text(
                            "Nothing noteworthy right now.",
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onPrimaryContainer.copy(alpha = 0.7f),
                        )
                    } else {
                        allFacts.forEach { fact ->
                            Row(
                                horizontalArrangement = Arrangement.spacedBy(8.dp),
                                verticalAlignment = Alignment.Top,
                            ) {
                                Text(
                                    "•",
                                    style = MaterialTheme.typography.bodySmall,
                                    color = MaterialTheme.colorScheme.onPrimaryContainer.copy(alpha = 0.6f),
                                )
                                Text(
                                    fact,
                                    style = MaterialTheme.typography.bodySmall,
                                    color = MaterialTheme.colorScheme.onPrimaryContainer.copy(alpha = 0.85f),
                                )
                            }
                        }
                    }
                }
            }
        }
    }
}

// ───────────────────────────────────────────────────────────────────────────
// History card (used for recent activity feed)
// ───────────────────────────────────────────────────────────────────────────

@Composable
private fun HistoryCard(
    item: com.secondbrain.app.orchestrator.ActivityEntry,
    onNavigate: (route: String, rowId: Long?) -> Unit = { _, _ -> },
) {
    val accentColor = kindAccentColor(item.kind)
    val target = remember(item.id) { resolveTarget(item) }
    val clickModifier = if (target != null) {
        Modifier.clickable { onNavigate(target.first, target.second) }
    } else Modifier
    Card(
        modifier = Modifier.fillMaxWidth().then(clickModifier),
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface),
        shape = RoundedCornerShape(10.dp),
        elevation = CardDefaults.cardElevation(defaultElevation = 1.dp),
    ) {
        Row(Modifier.fillMaxWidth().height(IntrinsicSize.Min)) {
            Box(Modifier.width(4.dp).fillMaxHeight().background(accentColor))
            Column(Modifier.weight(1f).padding(horizontal = 12.dp, vertical = 10.dp)) {
                Row(
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(6.dp),
                ) {
                    Text(
                        "> ${item.inputText}",
                        style = MaterialTheme.typography.bodyMedium.copy(fontWeight = FontWeight.Medium),
                        modifier = Modifier.weight(1f),
                        maxLines = 2,
                        overflow = TextOverflow.Ellipsis,
                    )
                    if (item.kind != null) {
                        Surface(
                            color = accentColor.copy(alpha = 0.15f),
                            shape = RoundedCornerShape(4.dp),
                        ) {
                            Text(
                                item.kind,
                                modifier = Modifier.padding(horizontal = 6.dp, vertical = 2.dp),
                                style = MaterialTheme.typography.labelSmall,
                                color = accentColor,
                            )
                        }
                    }
                }
                Spacer(Modifier.height(4.dp))
                Text(
                    item.responseText,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                Spacer(Modifier.height(4.dp))
                Text(
                    formatTimestampForDisplay(item.createdAt),
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.6f),
                )
            }
        }
    }
}

/**
 * Decide whether a Home activity row should deep-link, and to where.
 *
 * Three sources, tried in order until one yields a route:
 *
 * 1. **Orchestrator metadata** — the Home-input pipeline writes
 *    `target_route` + `target_row_id` into `metadata_json`. When present
 *    we honour it directly so the destination screen can highlight the
 *    affected row.
 *
 * 2. **Input-text tag prefix** — works for any historical Home-input row
 *    (orchestrator logs `kind="write"` / `"query"` which don't map to a
 *    single domain on their own; the chip prefix in the input does).
 *    Also picks up the rare `kind = null` rows.
 *
 * 3. **`kind` column** — covers page-CRUD writes (Add/Edit/toggle on
 *    Buy / Ledger / Weights / Todos / Notes / Expenses, all of which
 *    set a domain-specific `kind`) and the orchestrator note bypass.
 *
 * Always returns null for deletions / clears: the row no longer exists,
 * so navigation would land on an unrelated entry. Detected by an exact
 * `Deleted ` or `Cleared ` prefix (matches every per-screen
 * `logActivity("Deleted X", …)` / `("Cleared X", …)` call site,
 * case-sensitive so a user note starting with "deleted my…" stays
 * clickable).
 */
private fun resolveTarget(item: com.secondbrain.app.orchestrator.ActivityEntry): Pair<String, Long?>? {
    val input = item.inputText
    if (input.startsWith("Deleted ") || input.startsWith("Cleared ")) return null
    if (item.kind == "settings" || item.kind == "settings_error") return null

    // 1) Explicit metadata wins (carries row id for the highlight flash).
    parseMetadataTarget(item.metadataJson)?.let { return it }

    // 2) Tag prefix in the input text (covers historical Home submissions
    //    where the orchestrator logged kind="write" / "query" without
    //    enough context to derive a route from kind alone).
    inputTagToRoute(input)?.let { return it to null }

    // 3) Fall back to the `kind` column.
    val route = kindToRoute(item.kind) ?: return null
    return route to null
}

private fun parseMetadataTarget(metadataJson: String?): Pair<String, Long?>? {
    if (metadataJson.isNullOrBlank()) return null
    return try {
        val o = JSONObject(metadataJson)
        val route = o.optString("target_route", "").ifBlank { null } ?: return null
        val id = if (o.has("target_row_id") && !o.isNull("target_row_id"))
            o.optLong("target_row_id") else null
        route to id
    } catch (_: Throwable) { null }
}

/**
 * Pull the chip tag (`expense:`, `buy:`, `todo:`, `weight:`, `ledger:`,
 * `note:`) off the front of the user's input and map it to a route.
 * `ask:` deliberately returns null — without metadata we don't know
 * which domain it queried.
 */
private fun inputTagToRoute(input: String): String? {
    val head = input.trimStart().substringBefore(':', "").trim().lowercase()
    return when (head) {
        "expense" -> "expenses"
        "buy"     -> "buy"
        "todo", "task" -> "todos"
        "weight"  -> "weights"
        "ledger"  -> "ledger"
        "note"    -> "notes"
        else      -> null
    }
}

/** Map an `activity_log.kind` to the matching nav route, or null if non-navigable. */
private fun kindToRoute(kind: String?): String? = when (kind) {
    "expense" -> "expenses"
    "buy"     -> "buy"
    "todo"    -> "todos"
    "weight"  -> "weights"
    "ledger"  -> "ledger"
    "note"    -> "notes"
    else      -> null  // query / write / unknown / clarify_resolution / null
}

private fun kindAccentColor(kind: String?): Color = when (kind) {
    "todo"     -> Color(0xFF26A69A)
    "expense"  -> Color(0xFFFF8F00)
    "note"     -> Color(0xFF5C6BC0)
    "weight"   -> Color(0xFF8E24AA)
    "buy"      -> Color(0xFFEF5350)
    "ledger"   -> Color(0xFF00897B)
    "query"    -> Color(0xFF1E88E5)
    "write"    -> Color(0xFF43A047)
    "settings" -> Color(0xFF757575)
    else       -> Color(0xFF9E9E9E)
}

// ───────────────────────────────────────────────────────────────────────────
// Pending bubble + undo chip
// ───────────────────────────────────────────────────────────────────────────

@Composable
private fun UndoChip(undo: UndoBanner?, onClick: () -> Unit) {
    if (undo == null) return
    Surface(
        color = MaterialTheme.colorScheme.secondaryContainer,
        modifier = Modifier.fillMaxWidth(),
        shape = RoundedCornerShape(8.dp),
    ) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .clickable { onClick() }
                .padding(horizontal = 12.dp, vertical = 8.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Icon(Icons.Filled.Undo, contentDescription = "Undo")
            Spacer(Modifier.width(8.dp))
            Text(undo.label, style = MaterialTheme.typography.bodyMedium)
            Spacer(Modifier.weight(1f))
            Text("Tap to revert · 5s", style = MaterialTheme.typography.labelSmall)
        }
    }
}

@Composable
private fun PendingBubble(p: PendingItem, progress: String = "") {
    ElevatedCard(
        colors = CardDefaults.elevatedCardColors(
            containerColor = MaterialTheme.colorScheme.secondaryContainer,
        ),
    ) {
        Column(Modifier.padding(12.dp)) {
            Text("> ${p.composed}", style = MaterialTheme.typography.bodyMedium)
            Spacer(Modifier.height(4.dp))
            when (p.status) {
                PendingStatus.QUEUED -> Text("queued…", style = MaterialTheme.typography.labelSmall)
                PendingStatus.PROCESSING -> {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        ThreeDotPulse()
                        Spacer(Modifier.width(6.dp))
                        Text("processing", style = MaterialTheme.typography.labelSmall)
                    }
                    if (progress.isNotBlank()) {
                        Text(progress, style = MaterialTheme.typography.labelSmall, modifier = Modifier.padding(top = 4.dp))
                    }
                }
                PendingStatus.DONE   -> Text(p.response ?: "", style = MaterialTheme.typography.bodySmall)
                PendingStatus.FAILED -> Text(p.response ?: "Failed.", style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.error)
            }
        }
    }
}

@Composable
private fun ThreeDotPulse() {
    val transition = rememberInfiniteTransition(label = "dots")
    val phase by transition.animateValue(
        initialValue = 0, targetValue = 4, typeConverter = Int.VectorConverter,
        animationSpec = infiniteRepeatable(
            animation = tween(durationMillis = 900, easing = LinearEasing),
            repeatMode = RepeatMode.Restart,
        ),
        label = "phase",
    )
    Text(".".repeat((phase % 4).coerceIn(0, 3)).padEnd(3), style = MaterialTheme.typography.bodyMedium)
}

// ───────────────────────────────────────────────────────────────────────────
// Compact 2×3 tile grid
// ───────────────────────────────────────────────────────────────────────────

@Composable
private fun CompactTilesGrid(summary: TileSummary, onTileClick: (String) -> Unit) {
    val tiles = listOf(
        TileSpec("todos",    "Todos",    Icons.Filled.CheckBox,       summary.todo),
        TileSpec("expenses", "Expenses", Icons.Filled.AttachMoney,    summary.expense),
        TileSpec("buy",      "Buy",      Icons.Filled.ShoppingCart,   summary.buy),
        TileSpec("weights",  "Weights",  Icons.Filled.MonitorWeight,  summary.weight),
        TileSpec("notes",    "Notes",    Icons.Filled.Edit,           summary.notes),
        TileSpec("ledger",   "Ledger",   Icons.Filled.AccountBalance, summary.ledger),
    )
    Column(Modifier.fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(4.dp)) {
        tiles.chunked(3).forEach { rowTiles ->
            Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(4.dp)) {
                rowTiles.forEach { spec ->
                    Tile(spec = spec, modifier = Modifier.weight(1f), onClick = { onTileClick(spec.route) })
                }
                repeat(3 - rowTiles.size) { Spacer(Modifier.weight(1f)) }
            }
        }
    }
}

private data class TileSpec(val route: String, val title: String, val icon: ImageVector, val summary: String)

@Composable
private fun Tile(spec: TileSpec, modifier: Modifier, onClick: () -> Unit) {
    ElevatedCard(modifier = modifier.height(72.dp).clickable { onClick() }) {
        Column(Modifier.padding(8.dp).fillMaxSize(), verticalArrangement = Arrangement.spacedBy(2.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Icon(spec.icon, contentDescription = null, modifier = Modifier.size(16.dp))
                Spacer(Modifier.width(4.dp))
                Text(spec.title, style = MaterialTheme.typography.labelLarge, maxLines = 1)
            }
            Text(spec.summary, style = MaterialTheme.typography.labelSmall, maxLines = 2)
        }
    }
}

// ───────────────────────────────────────────────────────────────────────────
// Bottom input bar
// ───────────────────────────────────────────────────────────────────────────

@Composable
private fun HomeInputBar(
    input: String,
    chips: Set<Tag>,
    isProcessing: Boolean,
    onChipTap: (Tag) -> Unit,
    onInputChanged: (String) -> Unit,
    onSend: () -> Unit,
    onCancel: () -> Unit,
    onCopyLogs: () -> Unit,
) {
    Surface(color = MaterialTheme.colorScheme.surface, tonalElevation = 3.dp, shadowElevation = 6.dp) {
        Column(Modifier.fillMaxWidth().padding(8.dp)) {
            ChipRow(active = chips, onTap = onChipTap)

            val activeOrdered = orderActive(chips)
            if (activeOrdered.isNotEmpty()) {
                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(top = 6.dp)
                        .horizontalScroll(rememberScrollState()),
                    horizontalArrangement = Arrangement.spacedBy(6.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    activeOrdered.forEach { tag ->
                        InputChip(
                            selected = true,
                            onClick = { onChipTap(tag) },
                            label = { Text(tag.tagWithColon, style = MaterialTheme.typography.labelSmall) },
                            trailingIcon = {
                                Icon(Icons.Filled.Close, contentDescription = "Remove ${tag.tagWithColon}",
                                    modifier = Modifier.size(14.dp))
                            },
                        )
                    }
                }
            }

            OutlinedTextField(
                value = input, onValueChange = onInputChanged,
                placeholder = { Text("Type a note or query…") },
                modifier = Modifier.fillMaxWidth().padding(top = 4.dp),
                minLines = 1, maxLines = 4,
            )
            Row(Modifier.fillMaxWidth().padding(top = 4.dp), verticalAlignment = Alignment.CenterVertically) {
                TextButton(onClick = onCopyLogs) {
                    Icon(Icons.Filled.ContentCopy, contentDescription = null)
                    Spacer(Modifier.width(4.dp))
                    Text("Copy logs")
                }
                Spacer(Modifier.weight(1f))
                if (isProcessing) {
                    OutlinedButton(onClick = onCancel) { Text("Cancel") }
                    Spacer(Modifier.width(8.dp))
                }
                val hasTag = chips.isNotEmpty()
                Button(enabled = input.isNotBlank() && hasTag, onClick = onSend) {
                    Text(if (input.isNotBlank() && !hasTag) "Add tag" else "Send")
                }
            }
        }
    }
}

private fun orderActive(active: Set<Tag>): List<Tag> {
    if (active.isEmpty()) return emptyList()
    val out = mutableListOf<Tag>()
    if (Tag.ASK in active) out += Tag.ASK
    active.firstOrNull { it != Tag.ASK }?.let { out += it }
    return out
}

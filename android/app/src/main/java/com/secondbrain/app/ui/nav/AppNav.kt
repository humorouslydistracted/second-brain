package com.secondbrain.app.ui.nav

import androidx.compose.foundation.layout.*
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.List
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.unit.dp
import androidx.navigation.NavHostController
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.currentBackStackEntryAsState
import androidx.navigation.compose.rememberNavController
import com.secondbrain.app.ui.activity.ActivityLogScreen
import com.secondbrain.app.ui.buy.BuyScreen
import com.secondbrain.app.ui.dashboard.DashboardScreen
import com.secondbrain.app.ui.expenses.ExpensesScreen
import com.secondbrain.app.ui.home.HomeScreen
import com.secondbrain.app.ui.ledger.LedgerScreen
import com.secondbrain.app.ui.notes.NotesScreen
import com.secondbrain.app.ui.people.PeopleScreen
import com.secondbrain.app.ui.settings.SettingsScreen
import com.secondbrain.app.ui.todos.TodosScreen
import com.secondbrain.app.ui.weights.WeightsScreen
import kotlinx.coroutines.launch

private data class Dest(val route: String, val label: String, val icon: ImageVector)

// Domain screens are reached via the 6 tiles on Home. Drawer keeps only the
// surfaces that don't have a tile: activity log, people, settings.
// "Home" is also listed so it's reachable from other screens via the drawer.
private val DESTINATIONS = listOf(
    Dest("home",      "Home",         Icons.Filled.Home),
    Dest("activity",  "Activity log", Icons.AutoMirrored.Filled.List),
    Dest("people",    "People",       Icons.Filled.Group),
    Dest("settings",  "Settings",     Icons.Filled.Settings),
)

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun AppNav() {
    val navController: NavHostController = rememberNavController()
    val drawerState = rememberDrawerState(initialValue = DrawerValue.Closed)
    val scope = rememberCoroutineScope()
    val backStack by navController.currentBackStackEntryAsState()
    val currentRoute = backStack?.destination?.route ?: "home"
    val currentLabel = DESTINATIONS.firstOrNull { it.route == currentRoute }?.label ?: "Second Brain"
    val onHome = currentRoute == "home"

    ModalNavigationDrawer(
        drawerState = drawerState,
        drawerContent = {
            ModalDrawerSheet {
                // App name at top
                Spacer(Modifier.height(12.dp))
                Text(
                    "Second Brain",
                    style = MaterialTheme.typography.titleLarge,
                    modifier = Modifier.padding(16.dp),
                )
                // Push all nav items to the bottom of the drawer
                Spacer(Modifier.weight(1f))
                HorizontalDivider()
                DESTINATIONS.forEach { d ->
                    NavigationDrawerItem(
                        icon = { Icon(d.icon, contentDescription = null) },
                        label = { Text(d.label) },
                        selected = d.route == currentRoute,
                        onClick = {
                            scope.launch { drawerState.close() }
                            if (d.route != currentRoute) {
                                navController.navigate(d.route) {
                                    popUpTo("home") { saveState = true }
                                    launchSingleTop = true
                                    restoreState = true
                                }
                            }
                        },
                        modifier = Modifier.padding(NavigationDrawerItemDefaults.ItemPadding),
                    )
                }
                Spacer(Modifier.height(8.dp))
            }
        },
    ) {
        Scaffold(
            topBar = {
                // On the home screen: no top bar (no title, no hamburger).
                // Home is accessed via swipe; user gets the full-bleed greeting.
                // On all other screens: standard top bar with hamburger for drawer access.
                if (!onHome) {
                    TopAppBar(
                        title = { Text(currentLabel) },
                        navigationIcon = {
                            IconButton(onClick = { scope.launch { drawerState.open() } }) {
                                Icon(Icons.Filled.Menu, contentDescription = "Open menu")
                            }
                        },
                    )
                }
            }
        ) { padding ->
            NavHost(
                navController = navController,
                startDestination = "home",
                modifier = Modifier.padding(padding).fillMaxSize(),
            ) {
                composable("home")      { HomeScreen(navController = navController) }
                composable("activity")  { ActivityLogScreen() }
                composable("settings")  { SettingsScreen() }
                composable("notes")     { NotesScreen() }
                composable("dashboard") { DashboardScreen() }
                composable("expenses")  { ExpensesScreen() }
                composable("ledger")    { LedgerScreen() }
                composable("weights")   { WeightsScreen() }
                composable("todos")     { TodosScreen() }
                composable("buy")       { BuyScreen() }
                composable("people")    { PeopleScreen() }
            }
        }
    }
}

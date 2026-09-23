using System.Diagnostics;
using System.Net;
using System.Net.Sockets;
using System.Text.Json;

namespace MedBox.Launcher;

internal static class Program
{
    private const int PreferredAppPort = 8765;
    private const int PreferredOllamaPort = 11555;
    private static readonly List<Process> Children = [];
    private static readonly object ChildLock = new();
    private static CancellationTokenSource Shutdown = new();

    public static async Task<int> Main()
    {
        Console.OutputEncoding = System.Text.Encoding.UTF8;
        Console.Title = "MedBox — station locale";

        using var single = new Mutex(true, "Local\\ESA-Horizon-MedBox", out var first);
        var bundleRoot = ResolveBundleRoot();
        var runDirectory = Path.Combine(bundleRoot, "data", "run");
        Directory.CreateDirectory(runDirectory);
        var portFile = Path.Combine(runDirectory, "medbox.port");

        if (!first)
        {
            OpenExisting(portFile);
            return 0;
        }

        AppDomain.CurrentDomain.ProcessExit += (_, _) => StopChildren();
        Console.CancelKeyPress += (_, args) =>
        {
            args.Cancel = true;
            Shutdown.Cancel();
            StopChildren();
        };

        var appRoot = Directory.Exists(Path.Combine(bundleRoot, "app"))
            ? Path.Combine(bundleRoot, "app")
            : bundleRoot;
        var logs = Path.Combine(bundleRoot, "logs");
        var data = Path.Combine(bundleRoot, "data");
        Directory.CreateDirectory(logs);
        Directory.CreateDirectory(data);

        var python = FirstExisting(
            Path.Combine(bundleRoot, "runtime", "python", "python.exe"),
            FindOnPath("python.exe"));
        var ollama = FirstExisting(
            Path.Combine(bundleRoot, "runtime", "ollama", "ollama.exe"),
            FindOnPath("ollama.exe"));
        var entry = Path.Combine(appRoot, "medbox.py");

        if (python is null || !File.Exists(entry))
        {
            Console.Error.WriteLine("MedBox ne peut pas démarrer : le runtime Python ou app/medbox.py est absent.");
            Console.Error.WriteLine($"Dossier inspecté : {bundleRoot}");
            return 2;
        }

        var appPort = FindAvailablePort(PreferredAppPort);
        var ollamaPort = FindAvailablePort(PreferredOllamaPort, appPort);
        await File.WriteAllTextAsync(portFile, appPort.ToString());

        var common = new Dictionary<string, string>
        {
            ["MEDBOX_PORT"] = appPort.ToString(),
            ["MEDBOX_OLLAMA_HOST"] = $"http://127.0.0.1:{ollamaPort}",
            ["MEDBOX_DATABASE"] = Path.Combine(data, "medbox.db"),
            ["PYTHONUTF8"] = "1",
            ["PYTHONUNBUFFERED"] = "1",
            // The embeddable runtime still honours the per-user site-packages of
            // whoever is logged in. Without this, the bundle imports whatever that
            // person has installed and works on one laptop only.
            ["PYTHONNOUSERSITE"] = "1",
        };

        Console.WriteLine("MedBox — démarrage local hors ligne");
        Console.WriteLine($"Interface : http://127.0.0.1:{appPort}");

        if (ollama is not null)
        {
            var ollamaEnvironment = new Dictionary<string, string>(common)
            {
                ["OLLAMA_HOST"] = $"127.0.0.1:{ollamaPort}",
                ["OLLAMA_MODELS"] = Path.Combine(bundleRoot, "models", "ollama"),
            };
            StartChild(
                ollama,
                ["serve"],
                bundleRoot,
                ollamaEnvironment,
                Path.Combine(logs, "ollama.log"));
            Console.WriteLine("Assistant local : lancement et préchauffage en arrière-plan.");
        }
        else
        {
            Console.WriteLine("Assistant local : Ollama absent, mode dégradé déterministe.");
        }

        var server = StartChild(
            python,
            ["-s", entry, "--host", "127.0.0.1", "--port", appPort.ToString()],
            appRoot,
            common,
            Path.Combine(logs, "medbox.log"));

        var url = $"http://127.0.0.1:{appPort}";
        if (!await WaitForStation(url, TimeSpan.FromSeconds(35), Shutdown.Token))
        {
            Console.Error.WriteLine("L'interface n'a pas répondu. Consultez logs/medbox.log.");
            StopChildren();
            return 3;
        }

        Process.Start(new ProcessStartInfo(url) { UseShellExecute = true });
        Console.WriteLine("MedBox est ouvert. Laissez cette fenêtre active pendant la session.");
        Console.WriteLine("Ctrl+C arrête uniquement les processus lancés par MedBox.");

        try
        {
            await server.WaitForExitAsync(Shutdown.Token);
            if (!Shutdown.IsCancellationRequested)
                Console.Error.WriteLine($"Le serveur MedBox s'est arrêté (code {server.ExitCode}).");
            return server.ExitCode;
        }
        catch (OperationCanceledException)
        {
            return 0;
        }
        finally
        {
            StopChildren();
            try { File.Delete(portFile); } catch { }
        }
    }

    private static string ResolveBundleRoot()
    {
        var requested = Environment.GetEnvironmentVariable("MEDBOX_BUNDLE_ROOT");
        if (!string.IsNullOrWhiteSpace(requested))
            return Path.GetFullPath(requested);
        return Path.GetFullPath(AppContext.BaseDirectory);
    }

    private static void OpenExisting(string portFile)
    {
        if (!File.Exists(portFile) || !int.TryParse(File.ReadAllText(portFile), out var port))
        {
            Console.Error.WriteLine("Une session MedBox existe déjà, mais son adresse est indisponible.");
            return;
        }
        Process.Start(new ProcessStartInfo($"http://127.0.0.1:{port}") { UseShellExecute = true });
    }

    private static int FindAvailablePort(int preferred, int excluded = -1)
    {
        for (var candidate = preferred; candidate < preferred + 300; candidate++)
        {
            if (candidate == excluded) continue;
            try
            {
                var listener = new TcpListener(IPAddress.Loopback, candidate);
                listener.Start();
                listener.Stop();
                return candidate;
            }
            catch (SocketException) { }
        }
        throw new InvalidOperationException("Aucun port local disponible pour MedBox.");
    }

    private static Process StartChild(
        string executable,
        IReadOnlyList<string> arguments,
        string workingDirectory,
        IReadOnlyDictionary<string, string> environment,
        string logPath)
    {
        var start = new ProcessStartInfo(executable)
        {
            WorkingDirectory = workingDirectory,
            UseShellExecute = false,
            CreateNoWindow = true,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
        };
        foreach (var argument in arguments) start.ArgumentList.Add(argument);
        foreach (var pair in environment) start.Environment[pair.Key] = pair.Value;

        var process = new Process { StartInfo = start, EnableRaisingEvents = true };
        if (!process.Start()) throw new InvalidOperationException($"Impossible de lancer {executable}");
        lock (ChildLock) Children.Add(process);
        _ = Pump(process.StandardOutput, logPath);
        _ = Pump(process.StandardError, logPath);
        return process;
    }

    private static async Task Pump(StreamReader reader, string logPath)
    {
        while (await reader.ReadLineAsync() is { } line)
        {
            try
            {
                await File.AppendAllTextAsync(
                    logPath,
                    $"{DateTimeOffset.Now:O}  {line}{Environment.NewLine}");
            }
            catch { }
        }
    }

    private static async Task<bool> WaitForStation(
        string url,
        TimeSpan ceiling,
        CancellationToken cancellationToken)
    {
        using var client = new HttpClient { Timeout = TimeSpan.FromSeconds(1.5) };
        var until = DateTime.UtcNow + ceiling;
        while (DateTime.UtcNow < until && !cancellationToken.IsCancellationRequested)
        {
            try
            {
                var json = await client.GetStringAsync($"{url}/api/status", cancellationToken);
                using var document = JsonDocument.Parse(json);
                if (document.RootElement.TryGetProperty("ship", out _)) return true;
            }
            catch { }
            await Task.Delay(300, cancellationToken);
        }
        return false;
    }

    private static string? FirstExisting(params string?[] candidates) =>
        candidates.FirstOrDefault(candidate => !string.IsNullOrWhiteSpace(candidate) && File.Exists(candidate));

    private static string? FindOnPath(string name)
    {
        foreach (var folder in (Environment.GetEnvironmentVariable("PATH") ?? "").Split(Path.PathSeparator))
        {
            if (string.IsNullOrWhiteSpace(folder)) continue;
            try
            {
                var candidate = Path.Combine(folder.Trim('"'), name);
                if (File.Exists(candidate)) return candidate;
            }
            catch { }
        }
        return null;
    }

    private static void StopChildren()
    {
        lock (ChildLock)
        {
            foreach (var process in Children.AsEnumerable().Reverse())
            {
                try
                {
                    if (!process.HasExited) process.Kill(entireProcessTree: true);
                }
                catch { }
                finally { process.Dispose(); }
            }
            Children.Clear();
        }
    }
}

using System;
using System.Diagnostics;
using System.IO;
using System.Net;
using System.Text;
using System.Threading;

public static class PaperDownloaderNativeHost
{
    private const string RequestType = "ensureService";
    private const string DefaultHost = "127.0.0.1";
    private const int DefaultPort = 8765;
    private const int StartupTimeoutMs = 20000;
    private const int PollIntervalMs = 500;

    public static int Main()
    {
        try
        {
            var requestJson = ReadMessage();
            if (requestJson.IndexOf(RequestType, StringComparison.OrdinalIgnoreCase) < 0)
            {
                WriteJson("{\"ok\":false,\"error\":\"Unknown native host request\"}");
                return 1;
            }

            var repoRoot = ResolveRepoRoot();
            var backendUrl = BuildBackendUrl(repoRoot);
            var health = ProbeHealth(backendUrl);
            if (health != null)
            {
                WriteJson("{\"ok\":true,\"backendUrl\":\"" + JsonEscape(backendUrl) + "\",\"serviceStarted\":false,\"health\":" + health + "}");
                return 0;
            }

            StartService(repoRoot);
            var stopwatch = Stopwatch.StartNew();
            while (stopwatch.ElapsedMilliseconds < StartupTimeoutMs)
            {
                health = ProbeHealth(backendUrl);
                if (health != null)
                {
                    WriteJson("{\"ok\":true,\"backendUrl\":\"" + JsonEscape(backendUrl) + "\",\"serviceStarted\":true,\"health\":" + health + "}");
                    return 0;
                }

                Thread.Sleep(PollIntervalMs);
            }

            WriteJson("{\"ok\":false,\"error\":\"Timed out waiting for local service health check.\"}");
            return 1;
        }
        catch (Exception ex)
        {
            WriteJson("{\"ok\":false,\"error\":\"" + JsonEscape(ex.Message) + "\"}");
            return 1;
        }
    }

    private static string ResolveRepoRoot()
    {
        var exeDir = Path.GetDirectoryName(Process.GetCurrentProcess().MainModule.FileName);
        if (string.IsNullOrEmpty(exeDir))
        {
            throw new InvalidOperationException("Could not resolve native host executable directory.");
        }

        var repoRoot = Directory.GetParent(exeDir);
        if (repoRoot == null)
        {
            throw new InvalidOperationException("Could not resolve repository root from native host executable path.");
        }

        return repoRoot.FullName;
    }

    private static string BuildBackendUrl(string repoRoot)
    {
        var envPath = Path.Combine(repoRoot, ".env");
        var port = DefaultPort;
        if (File.Exists(envPath))
        {
            foreach (var rawLine in File.ReadAllLines(envPath))
            {
                var line = rawLine.Trim();
                if (line.Length == 0 || line.StartsWith("#"))
                {
                    continue;
                }

                var separator = line.IndexOf('=');
                if (separator <= 0)
                {
                    continue;
                }

                var key = line.Substring(0, separator).Trim();
                var value = line.Substring(separator + 1).Trim().Trim('"');
                int parsedPort;
                if (string.Equals(key, "PORT", StringComparison.OrdinalIgnoreCase) && int.TryParse(value, out parsedPort))
                {
                    port = parsedPort;
                }
            }
        }

        return "http://" + DefaultHost + ":" + port.ToString();
    }

    private static string ProbeHealth(string backendUrl)
    {
        var request = WebRequest.CreateHttp(backendUrl + "/health");
        request.Method = "GET";
        request.Timeout = 2000;
        request.ReadWriteTimeout = 2000;
        try
        {
            using (var response = (HttpWebResponse)request.GetResponse())
            using (var stream = response.GetResponseStream())
            using (var reader = new StreamReader(stream, Encoding.UTF8))
            {
                return reader.ReadToEnd();
            }
        }
        catch
        {
            return null;
        }
    }

    private static void StartService(string repoRoot)
    {
        var pythonPath = Path.Combine(repoRoot, ".venv", "Scripts", "python.exe");
        if (!File.Exists(pythonPath))
        {
            throw new FileNotFoundException("Python environment not found for local service.", pythonPath);
        }

        var startInfo = new ProcessStartInfo
        {
            FileName = pythonPath,
            Arguments = "-m paperdownloader.cli",
            WorkingDirectory = repoRoot,
            CreateNoWindow = true,
            UseShellExecute = false,
            WindowStyle = ProcessWindowStyle.Hidden,
        };
        startInfo.EnvironmentVariables["PAPERDOWNLOADER_SERVICE_MODE"] = "1";

        Process.Start(startInfo);
    }

    private static string ReadMessage()
    {
        using (var stdin = Console.OpenStandardInput())
        {
            var lengthBytes = ReadExact(stdin, 4);
            var length = BitConverter.ToInt32(lengthBytes, 0);
            var payload = ReadExact(stdin, length);
            return Encoding.UTF8.GetString(payload);
        }
    }

    private static byte[] ReadExact(Stream stream, int length)
    {
        var buffer = new byte[length];
        var offset = 0;
        while (offset < length)
        {
            var read = stream.Read(buffer, offset, length - offset);
            if (read <= 0)
            {
                throw new EndOfStreamException("Incomplete native messaging payload.");
            }

            offset += read;
        }

        return buffer;
    }

    private static void WriteJson(string json)
    {
        var payload = Encoding.UTF8.GetBytes(json);
        using (var stdout = Console.OpenStandardOutput())
        {
            stdout.Write(BitConverter.GetBytes(payload.Length), 0, 4);
            stdout.Write(payload, 0, payload.Length);
            stdout.Flush();
        }
    }

    private static string JsonEscape(string value)
    {
        if (value == null)
        {
            return string.Empty;
        }

        return value
            .Replace("\\", "\\\\")
            .Replace("\"", "\\\"")
            .Replace("\r", "\\r")
            .Replace("\n", "\\n");
    }
}

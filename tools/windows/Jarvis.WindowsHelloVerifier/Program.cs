using System.Text.Json;
using System.Windows.Forms;
using Windows.Security.Credentials.UI;

internal sealed record VerificationRequest(string Message);
internal sealed record VerificationResponse(string Status, string Reason);

internal static class Program
{
    [STAThread]
    private static async Task<int> Main()
    {
        try
        {
            var request = JsonSerializer.Deserialize<VerificationRequest>(
                await Console.In.ReadToEndAsync(),
                new JsonSerializerOptions { PropertyNameCaseInsensitive = true }
            );
            if (request is null || string.IsNullOrWhiteSpace(request.Message))
            {
                return Write("error", "invalid_request", 2);
            }

            var availability = await UserConsentVerifier.CheckAvailabilityAsync();
            if (availability != UserConsentVerifierAvailability.Available)
            {
                return availability switch
                {
                    UserConsentVerifierAvailability.NotConfiguredForUser =>
                        Write("not_configured", "not_configured_for_user", 0),
                    UserConsentVerifierAvailability.DeviceBusy =>
                        Write("unavailable", "device_busy", 0),
                    UserConsentVerifierAvailability.DisabledByPolicy =>
                        Write("unavailable", "disabled_by_policy", 0),
                    UserConsentVerifierAvailability.DeviceNotPresent =>
                        Write("unavailable", "device_not_present", 0),
                    _ => Write("unavailable", "availability_unknown", 0),
                };
            }

            Application.SetHighDpiMode(HighDpiMode.SystemAware);
            using var owner = new Form
            {
                ShowInTaskbar = false,
                FormBorderStyle = FormBorderStyle.FixedToolWindow,
                StartPosition = FormStartPosition.Manual,
                Location = new System.Drawing.Point(-32000, -32000),
                Size = new System.Drawing.Size(1, 1),
                Opacity = 0,
            };
            var hwnd = owner.Handle;
            var result = await UserConsentVerifierInterop.RequestVerificationForWindowAsync(
                hwnd,
                request.Message
            );
            return result switch
            {
                UserConsentVerificationResult.Verified =>
                    Write("verified", "verified", 0),
                UserConsentVerificationResult.Canceled =>
                    Write("canceled", "user_canceled", 0),
                UserConsentVerificationResult.RetriesExhausted =>
                    Write("retries_exhausted", "retries_exhausted", 0),
                UserConsentVerificationResult.NotConfiguredForUser =>
                    Write("not_configured", "not_configured_for_user", 0),
                UserConsentVerificationResult.DeviceBusy =>
                    Write("unavailable", "device_busy", 0),
                UserConsentVerificationResult.DeviceNotPresent =>
                    Write("unavailable", "device_not_present", 0),
                UserConsentVerificationResult.DisabledByPolicy =>
                    Write("unavailable", "disabled_by_policy", 0),
                _ => Write("failed", "verification_failed", 0),
            };
        }
        catch (Exception ex)
        {
            return Write("error", ex.GetType().Name, 1);
        }
    }

    private static int Write(string status, string reason, int exitCode)
    {
        Console.Out.Write(
            JsonSerializer.Serialize(new VerificationResponse(status, reason))
        );
        return exitCode;
    }
}

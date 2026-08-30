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
            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);

            VerificationResponse? response = null;
            using var owner = new Form
            {
                ShowInTaskbar = false,
                FormBorderStyle = FormBorderStyle.FixedToolWindow,
                StartPosition = FormStartPosition.CenterScreen,
                Size = new System.Drawing.Size(1, 1),
                Opacity = 0.01,
                TopMost = true,
            };

            owner.Shown += async (_, _) =>
            {
                try
                {
                    owner.Activate();
                    var result =
                        await UserConsentVerifierInterop.RequestVerificationForWindowAsync(
                            owner.Handle,
                            request.Message
                        );
                    response = Map(result);
                }
                catch (Exception ex)
                {
                    response = new VerificationResponse("error", ex.GetType().Name);
                }
                finally
                {
                    owner.Close();
                }
            };

            Application.Run(owner);
            var finalResponse = response ?? new VerificationResponse(
                "error",
                "verification_window_closed_without_result"
            );
            return Write(finalResponse.Status, finalResponse.Reason, 0);
        }
        catch (Exception ex)
        {
            return Write("error", ex.GetType().Name, 1);
        }
    }

    private static VerificationResponse Map(UserConsentVerificationResult result)
    {
        return result switch
        {
            UserConsentVerificationResult.Verified =>
                new VerificationResponse("verified", "verified"),
            UserConsentVerificationResult.Canceled =>
                new VerificationResponse("canceled", "user_canceled"),
            UserConsentVerificationResult.RetriesExhausted =>
                new VerificationResponse("retries_exhausted", "retries_exhausted"),
            UserConsentVerificationResult.NotConfiguredForUser =>
                new VerificationResponse("not_configured", "not_configured_for_user"),
            UserConsentVerificationResult.DeviceBusy =>
                new VerificationResponse("unavailable", "device_busy"),
            UserConsentVerificationResult.DeviceNotPresent =>
                new VerificationResponse("unavailable", "device_not_present"),
            UserConsentVerificationResult.DisabledByPolicy =>
                new VerificationResponse("unavailable", "disabled_by_policy"),
            _ => new VerificationResponse("failed", "verification_failed"),
        };
    }

    private static int Write(string status, string reason, int exitCode)
    {
        Console.Out.Write(
            JsonSerializer.Serialize(new VerificationResponse(status, reason))
        );
        return exitCode;
    }
}

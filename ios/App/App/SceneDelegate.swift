import UIKit
import Capacitor

// UIScene lifecycle (required to launch when built with the iOS 27 SDK / Xcode 27).
// Matches the Capacitor 8.5+ template: https://capacitorjs.com/docs/updating/8-5
// URL opens and Universal Links now arrive here instead of AppDelegate, and are forwarded to
// Capacitor so App.addListener('appUrlOpen') and App.getLaunchUrl() keep working.
class SceneDelegate: UIResponder, UIWindowSceneDelegate {
    var window: UIWindow?

    func scene(_ scene: UIScene, willConnectTo session: UISceneSession, options connectionOptions: UIScene.ConnectionOptions) {
        guard let windowScene = scene as? UIWindowScene else { return }
        window = UIWindow(windowScene: windowScene)
        window?.rootViewController = CAPBridgeViewController()
        window?.makeKeyAndVisible()
        SceneDelegateProxy.shared.scene(scene, willConnectTo: session, options: connectionOptions)
    }

    func scene(_ scene: UIScene, openURLContexts URLContexts: Set<UIOpenURLContext>) {
        SceneDelegateProxy.shared.scene(scene, openURLContexts: URLContexts)
    }

    func scene(_ scene: UIScene, continue userActivity: NSUserActivity) {
        SceneDelegateProxy.shared.scene(scene, continue: userActivity)
    }
}

import { useMessage } from "@assistant-ui/react";
import { Check } from "lucide-react";
import {
  Children,
  cloneElement,
  isValidElement,
  useMemo,
  useState,
} from "react";
import Markdown from "react-markdown";
import type { Components } from "react-markdown";
import remarkBreaks from "remark-breaks";
import remarkGfm from "remark-gfm";
import { rehypeCitationMarkers } from "../../chat/citationMarkers";
import { copyText } from "../../chat/copyText";
import { useSessionUi } from "../../chat/sessionUi";
import {
  renderHighlightedText,
  useSearchHighlightQuery,
} from "../MessageList/searchHighlight";
import Citations from "../Citations/Citations";
import ExecutionSteps from "../ExecutionSteps/ExecutionSteps";
import Warnings from "../Warnings/Warnings";
import styles from "./AssistantMessage.module.css";

const REMARK_PLUGINS = [remarkGfm, remarkBreaks];

const highlightNode = (
  node: React.ReactNode,
  query: string,
): React.ReactNode => {
  if (typeof node === "string") {
    return renderHighlightedText(node, query, styles.searchHit);
  }

  if (Array.isArray(node)) {
    return node.map((child, index) => <>{highlightNode(child, query)}</>);
  }

  if (isValidElement(node)) {
    return cloneElement(
      node,
      node.props,
      Children.map(node.props.children, (child) => highlightNode(child, query)),
    );
  }

  return node;
};

const createMarkdownComponents = (query: string): Components => ({
  p: ({ children }) => <p>{highlightNode(children, query)}</p>,
  li: ({ children }) => <li>{highlightNode(children, query)}</li>,
  h1: ({ children }) => <h1>{highlightNode(children, query)}</h1>,
  h2: ({ children }) => <h2>{highlightNode(children, query)}</h2>,
  h3: ({ children }) => <h3>{highlightNode(children, query)}</h3>,
  h4: ({ children }) => <h4>{highlightNode(children, query)}</h4>,
  blockquote: ({ children }) => <blockquote>{highlightNode(children, query)}</blockquote>,
  td: ({ children }) => <td>{highlightNode(children, query)}</td>,
  th: ({ children }) => <th>{highlightNode(children, query)}</th>,
  a: ({ children, ...props }) => <a {...props}>{highlightNode(children, query)}</a>,
  code: ({ children, ...props }) => <code {...props}>{highlightNode(children, query)}</code>,
});

const MARKDOWN_COMPONENTS_FALLBACK: Components = {
  p: ({ children }) => <p>{children}</p>,
};

function CopyMessageIcon() {
  return (
    <svg
      width="16"
      height="16"
      viewBox="0 0 16 16"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      aria-hidden="true"
    >
      <path
        d="M10.6136 8.65314C10.6136 7.95752 10.6136 7.47352 10.5832 7.0973C10.5728 6.89248 10.5356 6.68991 10.4725 6.49475L10.4186 6.36738C10.2679 6.07232 10.0387 5.82452 9.75633 5.65119L9.63191 5.58065C9.47711 5.50227 9.2694 5.44642 8.90199 5.41605C8.52577 5.38568 8.04276 5.38568 7.34615 5.38568H4.57053C3.87393 5.38568 3.39091 5.38568 3.01469 5.41605C2.80987 5.42652 2.6073 5.46374 2.41214 5.52676L2.28477 5.58065C1.98971 5.7314 1.74191 5.96056 1.56858 6.24296L1.5 6.36738C1.42064 6.52219 1.36479 6.72989 1.33442 7.0973C1.30405 7.47352 1.30307 7.95654 1.30307 8.65314V11.4288C1.30307 12.1254 1.30307 12.6084 1.33442 12.9846C1.36479 13.353 1.42064 13.5597 1.49902 13.7145L1.5676 13.838C1.74101 14.1201 1.98889 14.3494 2.28477 14.5003L2.41214 14.5551C2.55323 14.6061 2.7384 14.6423 3.01469 14.6649C3.39091 14.6952 3.87393 14.6962 4.57053 14.6962H7.34615C8.04177 14.6962 8.52577 14.6962 8.90199 14.6649C9.27038 14.6345 9.47711 14.5787 9.63191 14.5003L9.75633 14.4317C10.0375 14.2583 10.2678 14.0104 10.4186 13.7145L10.4725 13.5871C10.5235 13.4461 10.5607 13.2609 10.5832 12.9846C10.6136 12.6084 10.6136 12.1254 10.6136 11.4288V8.65314ZM11.9167 10.6107C12.3625 10.6087 12.7034 10.6058 12.9846 10.5832C13.353 10.5529 13.5597 10.497 13.7145 10.4186L13.838 10.3491C14.1201 10.1757 14.3494 9.92779 14.5003 9.63191L14.5551 9.50454C14.6178 9.30933 14.6547 9.10677 14.6649 8.90199C14.6952 8.52577 14.6962 8.04276 14.6962 7.34615V4.57053C14.6962 3.87393 14.6962 3.39091 14.6649 3.01469C14.6547 2.80991 14.6178 2.60735 14.5551 2.41214L14.5003 2.28477C14.3495 1.98971 14.1204 1.74191 13.838 1.56858L13.7145 1.5C13.5597 1.42064 13.352 1.36479 12.9846 1.33442C12.6084 1.30405 12.1254 1.30307 11.4288 1.30307H8.65314C7.95752 1.30307 7.47352 1.30405 7.0973 1.33442C6.82101 1.35695 6.63584 1.3932 6.49475 1.44415L6.36738 1.49902C6.07232 1.64977 5.82452 1.87893 5.65119 2.16133L5.58065 2.28477C5.50227 2.43957 5.44642 2.64728 5.41605 3.01469C5.39352 3.29588 5.3896 3.63683 5.38764 4.08261H7.34615C8.0212 4.08261 8.56692 4.08261 9.00781 4.11788C9.45653 4.15511 9.85529 4.23251 10.2247 4.42063L10.4373 4.54016C10.9232 4.838 11.319 5.26517 11.5787 5.77464L11.6443 5.91474C11.7854 6.24492 11.8501 6.59861 11.8814 6.99148C11.9177 7.43237 11.9167 7.97809 11.9167 8.65314V10.6107ZM15.9993 7.34615C15.9993 8.0212 15.9993 8.56692 15.964 9.00781C15.9317 9.40069 15.868 9.75437 15.7269 10.0845L15.6613 10.2247C15.4016 10.7341 15.0048 11.1613 14.5199 11.4591L14.3053 11.5787C13.9369 11.7668 13.5391 11.8442 13.0904 11.8814C12.7602 11.9079 12.3713 11.9118 11.9147 11.9137C11.9118 12.3713 11.9079 12.7602 11.8814 13.0904C11.8491 13.4833 11.7854 13.837 11.6443 14.1662L11.5787 14.3053C11.319 14.8167 10.9232 15.2439 10.4373 15.5417L10.2247 15.6613C9.85529 15.8494 9.45653 15.9268 9.00781 15.964C8.56692 16.0003 8.0212 15.9993 7.34615 15.9993H4.57053C3.8945 15.9993 3.34976 15.9993 2.90887 15.964C2.51698 15.9317 2.16231 15.868 1.83311 15.7269L1.69301 15.6613C1.18404 15.4017 0.75654 15.0067 0.457545 14.5199L0.338016 14.3053C0.149904 13.9369 0.0725039 13.5391 0.0352735 13.0904C-0.000977159 12.6495 2.57649e-06 12.1038 2.57649e-06 11.4288V8.65314C2.57649e-06 7.97809 2.59139e-06 7.43237 0.0352735 6.99148C0.0725039 6.54276 0.149904 6.144 0.338016 5.77464L0.457545 5.56203C0.755388 5.07608 1.18256 4.68026 1.69301 4.42063L1.83311 4.35498C2.16231 4.2139 2.516 4.14924 2.90887 4.11788C3.23905 4.09143 3.62703 4.08653 4.08457 4.08457C4.08653 3.62703 4.09143 3.23905 4.11788 2.90887C4.15413 2.46015 4.23251 2.06237 4.42063 1.69399L4.54016 1.47844C4.838 0.993467 5.26517 0.597649 5.77464 0.338016L5.91474 0.272372C6.24492 0.131289 6.59861 0.0666255 6.99148 0.0352735C7.43237 -0.000977159 7.97809 2.57649e-06 8.65314 2.57649e-06H11.4288C12.1048 2.57649e-06 12.6495 2.59139e-06 13.0904 0.0352735C13.5391 0.0725039 13.9369 0.149904 14.3053 0.338016L14.5208 0.457545C15.0058 0.755388 15.4016 1.18256 15.6613 1.69301L15.7269 1.83311C15.868 2.16231 15.9327 2.516 15.964 2.90887C16.0003 3.34976 15.9993 3.89548 15.9993 4.57053V7.34615Z"
        fill="currentColor"
        fillOpacity="0.7"
      />
    </svg>
  );
}

function MessageActionIcon() {
  return (
    <svg
      width="15"
      height="16"
      viewBox="0 0 15 16"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      aria-hidden="true"
    >
      <path
        d="M8.08004 0.00456282L8.45234 0.0515907L8.62869 0.0780439C9.04415 0.154629 9.43958 0.315299 9.79071 0.550194C10.1418 0.78509 10.4413 1.08926 10.6706 1.44403C10.9 1.7988 11.0545 2.1967 11.1245 2.61331C11.1946 3.02992 11.1788 3.45645 11.0781 3.86673L11.0301 4.04015L10.5137 5.71845C10.8782 5.72237 11.1966 5.73021 11.4739 5.75176C11.9589 5.78998 12.387 5.87129 12.7691 6.07214L12.918 6.15542C13.2796 6.37223 13.5932 6.66038 13.8398 7.00231C14.0864 7.34425 14.2608 7.7328 14.3524 8.14431L14.3818 8.30303C14.4366 8.67533 14.3994 9.06037 14.3191 9.47873C14.2734 9.71452 14.2123 9.98003 14.1359 10.2753L13.8713 11.2648L13.499 12.6316C13.2658 13.4859 13.1052 14.109 12.8034 14.593L12.6653 14.7939C12.3751 15.1679 12.0039 15.4714 11.5797 15.6815L11.3945 15.7648C10.7969 16.0107 10.1013 15.9999 9.08918 15.9999H4.57058C3.89553 15.9999 3.34981 15.9999 2.90893 15.9637C2.51703 15.9313 2.16334 15.8677 1.83316 15.7266L1.69404 15.6609C1.18471 15.4015 0.756857 15.0065 0.457596 14.5195L0.338066 14.3059C0.149955 13.9366 0.0725547 13.5388 0.0353243 13.0911C5.33316e-05 12.6502 5.33186e-05 12.1035 5.33186e-05 11.4284V9.63255C5.33186e-05 8.91537 -0.00582513 8.42746 0.105866 8.01302L0.165631 7.81609C0.330228 7.33403 0.610868 6.89986 0.982821 6.55182C1.35477 6.20379 1.80662 5.95259 2.29854 5.82035L2.45824 5.7841C2.83936 5.71062 3.29005 5.71453 3.91807 5.71453C4.0513 5.71478 4.18223 5.67974 4.29753 5.61297C4.41284 5.5462 4.5084 5.45008 4.5745 5.33439L7.43536 0.32788L7.48925 0.24754C7.55888 0.160084 7.6497 0.0918617 7.75309 0.0493396C7.85648 0.00681749 7.96902 -0.00859508 8.08004 0.00456282ZM4.56862 12.0819C4.56862 12.8824 4.5745 13.1557 4.63034 13.3634L4.66561 13.4781C4.76132 13.7573 4.92412 14.0087 5.1397 14.2103C5.35529 14.4118 5.61707 14.5574 5.90206 14.6342L6.07645 14.6685C6.27926 14.6929 6.58298 14.6959 7.18357 14.6959H9.08918C10.2198 14.6959 10.597 14.6841 10.8968 14.5597L11.0046 14.5107C11.2495 14.3902 11.467 14.2148 11.6346 13.9973L11.7061 13.8945C11.8628 13.6378 11.9804 13.2429 12.241 12.2886L12.6143 10.9209L12.8739 9.95096C12.9445 9.67467 13.0003 9.4415 13.0395 9.23477C13.0983 8.92811 13.113 8.72236 13.1003 8.56658L13.0797 8.42648C12.9796 7.97768 12.7119 7.58409 12.3312 7.32622L12.1617 7.22531C12.0088 7.14497 11.7864 7.08324 11.372 7.05091C10.9536 7.01858 10.4089 7.0176 9.63294 7.0176C9.53109 7.01748 9.43069 6.99349 9.3398 6.94755C9.2489 6.90161 9.17005 6.83501 9.10955 6.75308C9.04906 6.67115 9.00861 6.57617 8.99146 6.47578C8.97431 6.37539 8.98093 6.27238 9.0108 6.17502L9.7848 3.65706L9.83378 3.45622C9.87755 3.2203 9.87359 2.978 9.82215 2.74363C9.77071 2.50927 9.67282 2.28759 9.53428 2.09169C9.39573 1.89578 9.21933 1.72963 9.0155 1.60304C8.81166 1.47645 8.58453 1.392 8.34751 1.35466L5.70415 5.98005C5.45275 6.41958 5.0481 6.75097 4.56764 6.91081L4.56862 12.0819ZM1.30312 11.4284C1.30312 12.125 1.3041 12.608 1.33545 12.9843C1.36484 13.3527 1.42069 13.5594 1.50005 13.7142L1.56863 13.8376C1.74107 14.1198 1.98992 14.3491 2.28483 14.4999L2.41219 14.5538C2.55328 14.6048 2.73845 14.642 3.01474 14.6645C3.24302 14.6831 3.50951 14.689 3.83969 14.692C3.66669 14.4482 3.52944 14.181 3.43211 13.8984L3.37235 13.7005C3.26065 13.286 3.26457 12.8001 3.26457 12.0819V7.0225C3.06177 7.02642 2.92166 7.0323 2.80997 7.04601L2.63558 7.07932C2.35041 7.15595 2.08843 7.30145 1.87266 7.50303C1.6569 7.70462 1.49396 7.95612 1.39815 8.23543L1.36386 8.35006C1.30802 8.55776 1.30214 8.83111 1.30214 9.63255L1.30312 11.4284Z"
        fill="currentColor"
        fillOpacity="0.7"
      />
    </svg>
  );
}

function MessageActionIconSecondary() {
  return (
    <svg
      width="15"
      height="16"
      viewBox="0 0 15 16"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      aria-hidden="true"
    >
      <path
        d="M9.83881 3.91712C9.83881 3.31653 9.83489 3.01281 9.80942 2.81098L9.77709 2.63561C9.70032 2.35062 9.55476 2.08884 9.35318 1.87325C9.15161 1.65767 8.90018 1.49487 8.62099 1.39916L8.50537 1.36487C8.29767 1.30903 8.0253 1.30315 7.22386 1.30315H5.31825C4.32871 1.30315 3.91721 1.31295 3.62819 1.39819L3.51062 1.43933C3.25588 1.54417 3.03054 1.70583 2.84831 1.91157L2.77287 2.00171C2.62395 2.19472 2.52401 2.44554 2.35844 3.01967L2.1664 3.71039L1.79312 5.07812C1.58835 5.82665 1.44629 6.35179 1.36791 6.76427C1.28953 7.1738 1.28953 7.40404 1.32676 7.57256L1.38065 7.76263C1.52761 8.19568 1.83525 8.55818 2.24478 8.77373L2.37509 8.83055C2.52205 8.88248 2.72486 8.92363 3.03544 8.94812C3.45379 8.98046 3.99853 8.98143 4.77449 8.98143C4.86991 8.98147 4.96415 9.00247 5.05055 9.04293C5.13696 9.0834 5.21343 9.14235 5.27455 9.21562C5.33566 9.28888 5.37994 9.37468 5.40426 9.46694C5.42857 9.55921 5.43232 9.65568 5.41525 9.74956L5.39663 9.82402L4.62263 12.342C4.5469 12.5879 4.52491 12.8473 4.55815 13.1024C4.59139 13.3576 4.67908 13.6027 4.81528 13.821C4.95149 14.0393 5.13302 14.2258 5.34759 14.3679C5.56216 14.51 5.80476 14.6042 6.05894 14.6444L8.7023 10.019L8.77481 9.90142C9.02854 9.51855 9.4031 9.2316 9.83881 9.08627V3.91712ZM14.4074 6.36649C14.4074 6.99353 14.4113 7.44519 14.3388 7.82631L14.3006 7.98503C14.1684 8.47685 13.9174 8.92862 13.5695 9.30057C13.2217 9.67251 12.7877 9.95321 12.3058 10.1179L12.1099 10.1787C11.6935 10.2894 11.2075 10.2845 10.4903 10.2845C10.374 10.2842 10.2591 10.3109 10.1547 10.3624C10.0504 10.4139 9.95936 10.4888 9.88878 10.5814L9.83391 10.6646L6.97305 15.6712C6.90875 15.7824 6.8132 15.8724 6.69825 15.9299C6.5833 15.9873 6.45401 16.0098 6.32641 15.9945L5.95607 15.9474C5.50694 15.8912 5.07557 15.7374 4.69224 15.4967C4.30891 15.256 3.98292 14.9343 3.73717 14.5541C3.49142 14.174 3.33187 13.7447 3.26971 13.2964C3.20755 12.848 3.2443 12.3915 3.37737 11.9589L3.89272 10.2796C3.5724 10.2793 3.25218 10.2685 2.93257 10.2473C2.50932 10.214 2.12917 10.1493 1.78332 9.99743L1.63832 9.92689C1.26488 9.73075 0.935466 9.46037 0.670281 9.13235C0.405096 8.80432 0.209739 8.42556 0.0961966 8.01932L0.0550474 7.8557C-0.0380287 7.43343 -0.00373757 6.99843 0.0883588 6.52031C0.178496 6.04611 0.337215 5.46316 0.536104 4.73521L0.908408 3.36748L1.09652 2.68949C1.27581 2.06441 1.44531 1.58924 1.74119 1.20517L1.8715 1.04841C2.18502 0.694726 2.57398 0.415498 3.01291 0.235224L3.24217 0.153905C3.78985 -0.0087334 4.43256 8.43865e-05 5.31923 8.43865e-05H9.83587C10.5119 8.43865e-05 11.0576 8.44027e-05 11.4985 0.0353553C11.9472 0.0725858 12.345 0.149986 12.7134 0.338097L12.927 0.457627C13.4129 0.75547 13.8088 1.18264 14.0694 1.69407L14.135 1.83319C14.2761 2.16239 14.3398 2.51608 14.3721 2.90896C14.4074 3.34984 14.4074 3.89556 14.4074 4.57061V6.36649ZM11.1409 8.97556C11.4681 8.96968 11.6337 8.95694 11.7709 8.92069L11.8855 8.88444C12.1648 8.78896 12.4163 8.62637 12.6181 8.41096C12.8198 8.19554 12.9656 7.93389 13.0426 7.64898L13.0749 7.47262C13.1004 7.27177 13.1043 6.96805 13.1043 6.36649V4.57061C13.1043 3.87401 13.1033 3.39099 13.073 3.01477C13.0625 2.80995 13.0253 2.60738 12.9622 2.41222L12.9084 2.28486C12.7576 1.98979 12.5284 1.74199 12.2461 1.56866L12.1226 1.50008C11.9678 1.42072 11.7601 1.36487 11.3927 1.3345C11.1178 1.31535 10.8423 1.30588 10.5668 1.30609C10.7774 1.60197 10.9391 1.93607 11.0351 2.29857L11.0713 2.45827C11.1242 2.73064 11.138 3.03828 11.1399 3.42039L11.1409 8.97556Z"
        fill="currentColor"
        fillOpacity="0.7"
      />
    </svg>
  );
}

function MessageActionIconTertiary() {
  return (
    <svg
      width="15"
      height="15"
      viewBox="0 0 15 15"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      aria-hidden="true"
    >
      <path
        d="M0.766299 13.7145V10.449C0.766299 10.0894 1.05826 9.79748 1.41783 9.79748H4.68333L4.81462 9.8112C4.96169 9.84129 5.09386 9.92125 5.18878 10.0376C5.2837 10.1539 5.33554 10.2994 5.33554 10.4495C5.33554 10.5996 5.2837 10.7451 5.18878 10.8614C5.09386 10.9778 4.96169 11.0577 4.81462 11.0878L4.68333 11.1005H2.69934C3.26097 11.7183 3.94541 12.2119 4.70883 12.5498C5.47225 12.8878 6.29783 13.0625 7.1327 13.063C10.1307 13.063 12.6056 10.8194 12.9671 7.9193L12.9965 7.79096C13.0481 7.63793 13.1547 7.50952 13.2956 7.43063C13.4365 7.35175 13.6017 7.328 13.7591 7.364C13.9165 7.4 14.055 7.49318 14.1476 7.62547C14.2402 7.75777 14.2804 7.91974 14.2604 8.07998L14.2114 8.41016C13.9227 10.0781 13.0542 11.5904 11.759 12.6803C10.4639 13.7702 8.82541 14.3676 7.1327 14.367C5.24441 14.3657 3.4299 13.6337 2.06936 12.3243V13.7155C2.06936 13.8883 2.00072 14.054 1.87853 14.1762C1.75635 14.2984 1.59063 14.367 1.41783 14.367C1.24503 14.367 1.07931 14.2984 0.957129 14.1762C0.834943 14.054 0.766299 13.8873 0.766299 13.7145ZM1.2983 6.4487C1.27687 6.6202 1.18818 6.77616 1.05175 6.88227C0.915327 6.98838 0.742337 7.03594 0.570839 7.01451C0.399341 6.99307 0.243383 6.90438 0.137275 6.76796C0.0311656 6.63153 -0.0164025 6.45854 0.0050347 6.28704L1.2983 6.4487ZM7.1327 0.00195959C9.08632 0.00195959 10.892 0.782819 12.2058 2.05257V0.651532C12.2058 0.478735 12.2745 0.313015 12.3967 0.190829C12.5189 0.0686433 12.6846 0 12.8574 0C13.0302 0 13.1959 0.0686433 13.3181 0.190829C13.4403 0.313015 13.5089 0.478735 13.5089 0.651532V3.91703C13.5089 4.08983 13.4403 4.25555 13.3181 4.37774C13.1959 4.49992 13.0302 4.56857 12.8574 4.56857H9.59187C9.41907 4.56857 9.25335 4.49992 9.13117 4.37774C9.00898 4.25555 8.94034 4.08983 8.94034 3.91703C8.94034 3.74424 9.00898 3.57852 9.13117 3.45633C9.25335 3.33414 9.41907 3.2655 9.59187 3.2655H11.5661C11.0044 2.64778 10.32 2.15414 9.55657 1.81621C8.79315 1.47828 7.96757 1.3035 7.1327 1.30306C5.70042 1.30326 4.31744 1.82611 3.24325 2.77349C2.16906 3.72087 1.47749 5.02768 1.2983 6.4487L0.651669 6.36738L0.0050347 6.28704C0.223626 4.55083 1.06837 2.95408 2.38072 1.79651C3.69307 0.638939 5.38278 0.000134616 7.1327 0"
        fill="currentColor"
        fillOpacity="0.7"
      />
    </svg>
  );
}

function TypingIndicator() {
  return (
    <div className={styles.typing} aria-label="Ассистент печатает" role="status">
      <span />
      <span />
      <span />
    </div>
  );
}

export default function AssistantMessage() {
  const text = useMessage((m) =>
    m.content
      .filter((part) => part.type === "text")
      .map((part) => ("text" in part ? part.text : ""))
      .join("\n"),
  );
  const id = useMessage((m) => m.id);
  const { traceByMessage, citationsByMessage, warningsByMessage, activeMessageId } =
    useSessionUi();
  const steps = traceByMessage.get(id) ?? [];
  const citations = citationsByMessage.get(id) ?? [];
  const warnings = warningsByMessage.get(id) ?? [];
  // Hard failures / "база недоступна" show as a banner at the START of the message
  // (deterministic, from metadata — never left to the LLM to phrase); soft
  // degradations stay as chips below the answer.
  const bannerWarnings = warnings.filter((w) => w.level === "error");
  const chipWarnings = warnings.filter((w) => w.level === "warning");
  const isActive = id === activeMessageId;
  const [isCopied, setIsCopied] = useState(false);
  const [isDisliked, setIsDisliked] = useState(false);
  const [isFeedbackOpen, setIsFeedbackOpen] = useState(false);
  const [feedbackText, setFeedbackText] = useState("");
  const searchQuery = useSearchHighlightQuery();

  // Inline [n] superscripts link to their citation card — only once the cards are
  // rendered (i.e. not while streaming) and only for markers that have a card.
  const markerSet = new Set(
    citations.map((c) => c.marker).filter((m): m is number => m != null),
  );
  const useMarkers = !isActive && markerSet.size > 0;
  const jumpToCitation = (marker: number) => {
    const el = document.getElementById(`citation-${marker}`);
    if (!el) return;
    el.scrollIntoView({ behavior: "smooth", block: "center" });
    el.classList.add(styles.flash);
    window.setTimeout(() => el.classList.remove(styles.flash), 1200);
  };

  // Markdown renders search highlighting (redesign) AND clickable citation
  // markers (backend) at once: start from the highlight components (or fallback),
  // then layer the citation `sup` handler when markers are active.
  const markdownComponents = useMemo<Components>(() => {
    const base: Components = searchQuery.trim()
      ? createMarkdownComponents(searchQuery)
      : { ...MARKDOWN_COMPONENTS_FALLBACK };
    if (useMarkers) {
      base.sup = ({ node, children, ...props }) => {
        const marker = node?.properties?.dataMarker;
        if (marker == null) return <sup {...props}>{children}</sup>;
        const n = Number(marker);
        return (
          <sup
            className={styles.citationMarker}
            role="button"
            tabIndex={0}
            onClick={() => jumpToCitation(n)}
            onKeyDown={(e) => {
              if (e.key === "Enter" || e.key === " ") jumpToCitation(n);
            }}
          >
            {n}
          </sup>
        );
      };
    }
    return base;
    // jumpToCitation only reads the DOM + styles, so it needn't be a dep.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchQuery, useMarkers]);

  const handleCopy = async () => {
    const copied = await copyText(text);
    if (!copied) return;

    setIsCopied(true);
    window.setTimeout(() => setIsCopied(false), 1600);
  };

  const handleDislike = () => {
    setIsDisliked(true);
    setIsFeedbackOpen(true);
  };

  const handleSubmitFeedback = () => {
    setIsFeedbackOpen(false);
    setFeedbackText("");
  };

  return (
    <>
      <div
        className={styles.row}
        data-chat-search-item="true"
        data-chat-search-text={text}
      >
        <div className={styles.content}>
          <ExecutionSteps steps={steps} running={isActive} />
          {!isActive ? <Warnings items={bannerWarnings} /> : null}
          <div className={styles.bubble}>
            {text ? (
              <Markdown
                remarkPlugins={REMARK_PLUGINS}
                rehypePlugins={useMarkers ? [[rehypeCitationMarkers, markerSet]] : []}
                components={markdownComponents}
              >
                {text}
              </Markdown>
            ) : isActive ? (
              <TypingIndicator />
            ) : null}
          </div>
          {!isActive ? <Warnings items={chipWarnings} /> : null}
          {!isActive ? <Citations items={citations} /> : null}
          <div className={styles.actions}>
            <button
              type="button"
              onClick={() => void handleCopy()}
              aria-label={isCopied ? "Скопировано" : "Копировать ответ"}
              title={isCopied ? "Скопировано" : "Копировать"}
              disabled={isActive}
            >
              {isCopied ? <Check size={16} /> : <CopyMessageIcon />}
            </button>
            <button
              type="button"
              aria-label="Нравится"
              title="Нравится"
              disabled={isActive}
            >
              <MessageActionIcon />
            </button>
            <button
              type="button"
              aria-label="Не нравится"
              title="Не нравится"
              disabled={isActive}
              className={isDisliked ? styles.activeNegative : undefined}
              onClick={handleDislike}
            >
              <MessageActionIconSecondary />
            </button>
            <button
              type="button"
              aria-label="Повторить ответ"
              title="Повторить ответ"
              disabled={isActive}
            >
              <MessageActionIconTertiary />
            </button>
          </div>
        </div>
      </div>
      {isFeedbackOpen ? (
        <div
          className={styles.feedbackOverlay}
          onClick={() => setIsFeedbackOpen(false)}
          role="presentation"
        >
          <div
            className={styles.feedbackModal}
            onClick={(event) => event.stopPropagation()}
            role="dialog"
            aria-modal="true"
            aria-labelledby="assistant-feedback-title"
          >
            <h3 id="assistant-feedback-title" className={styles.feedbackTitle}>
              Поделиться отзывом
            </h3>
            <textarea
              className={styles.feedbackInput}
              placeholder="Поделитесь подробностями"
              value={feedbackText}
              onChange={(event) => setFeedbackText(event.target.value)}
            />
            <button
              type="button"
              className={styles.feedbackSubmit}
              onClick={handleSubmitFeedback}
            >
              Отправить
            </button>
          </div>
        </div>
      ) : null}
    </>
  );
}
